"""
ReVolver Token Exchange Lambda

Handles the OAuth2 token exchange with Volvo ID, keeping the client_secret
server-side. Secrets are read from SSM Parameter Store (SecureString).

SSM Parameters (create once):
    /revolver/client-id        (SecureString) - Volvo app client ID
    /revolver/client-secret    (SecureString) - Volvo app client secret
    /revolver/vcc-api-key      (SecureString) - Volvo Connected Cars API key
    /revolver/redirect-uri     (String)       - OAuth redirect URI
    /revolver/allowed-origins  (String)       - Comma-separated allowed CORS origins
    /revolver/scopes           (String)       - Space-separated OAuth scopes (optional)
    /revolver/auth-endpoint    (String)       - Volvo authorization URL (optional)
    /revolver/token-endpoint   (String)       - Volvo token URL (optional)

Environment variables:
    SSM_PREFIX     - Parameter path prefix (default: /revolver)
    PAIRING_TABLE  - DynamoDB table for browser-login pairing

Browser-login pairing: login runs in the phone's browser,
tokens reach PebbleKit JS through a short-lived pairing item:
    POST action=pair_start                -> {code, secret}  (PebbleKit JS)
    POST grant_type=authorization_code&pair=<code>
                                          -> {ok: true}      (browser; tokens stored, never returned)
    POST action=pair_poll&code=&secret=   -> 202 pending | 200 tokens (once) | 404
"""

import json
import os
import re
import time
import base64
import hashlib
import hmac
import secrets
import urllib.request
import urllib.parse
import urllib.error

DEFAULT_TOKEN_ENDPOINT = "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/token"
DEFAULT_ALLOWED_ORIGINS = "https://piotrserafin.github.io,https://piotrserafin.dev"
DEFAULT_AUTH_ENDPOINT = "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth"

PAIR_TTL_SECONDS = 600
PAIR_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


_config = {}


def get_config():
    """Load config from SSM Parameter Store (cached after first call)."""
    global _config
    if _config:
        return _config

    import boto3

    ssm = boto3.client("ssm")
    prefix = os.environ.get("SSM_PREFIX", "/revolver")

    resp = ssm.get_parameters(
        Names=[
            f"{prefix}/client-id",
            f"{prefix}/client-secret",
            f"{prefix}/vcc-api-key",
            f"{prefix}/redirect-uri",
            f"{prefix}/allowed-origins",
            f"{prefix}/scopes",
            f"{prefix}/auth-endpoint",
            f"{prefix}/token-endpoint",
        ],
        WithDecryption=True,
    )

    for param in resp["Parameters"]:
        key = param["Name"].split("/")[-1]  # e.g. "client-id"
        _config[key] = param["Value"]

    return _config


# Current request origin (set per invocation)
_request_origin = ""


# ─── Handler ─────────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    """Handle config, token exchange, and token refresh requests."""
    try:
        return _handle(event)
    except Exception:
        # Never log unhandled exceptions — tracebacks may contain secrets/tokens
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "internal_error"}),
        }


def _handle(event):
    """Internal request handler."""
    global _request_origin
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")

    # Verify request origin
    origin = (event.get("headers") or {}).get("origin", "")
    config = get_config()
    allowed_origins = [
        o.strip()
        for o in config.get("allowed-origins", DEFAULT_ALLOWED_ORIGINS).split(",")
    ]

    if origin and origin not in allowed_origins:
        return cors_response(
            403, {"error": "forbidden", "detail": "Origin not allowed"}
        )

    _request_origin = origin if origin in allowed_origins else allowed_origins[0]

    # Handle CORS preflight
    if method == "OPTIONS":
        return cors_response(200, "")

    # GET — return public config (client_id, redirect_uri, scopes)
    if method == "GET":
        return handle_config()

    # POST — token exchange or refresh
    try:
        body = event.get("body", "")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        params = dict(urllib.parse.parse_qsl(body))
    except Exception:
        return cors_response(400, {"error": "invalid_request"})

    action = params.get("action", "")
    if action == "pair_start":
        return handle_pair_start()
    if action == "pair_poll":
        return handle_pair_poll(params)

    grant_type = params.get("grant_type", "")

    if grant_type == "authorization_code":
        return handle_auth_code(params)
    elif grant_type == "refresh_token":
        return handle_refresh(params)
    else:
        return cors_response(
            400,
            {
                "error": "unsupported_grant_type",
                "detail": f"Expected 'authorization_code' or 'refresh_token', got '{grant_type}'",
            },
        )


def handle_config():
    """Return public OAuth config (no secrets exposed)."""
    config = get_config()
    result = {
        "client_id": config.get("client-id", ""),
        "redirect_uri": config.get("redirect-uri", ""),
        "auth_endpoint": config.get("auth-endpoint", DEFAULT_AUTH_ENDPOINT),
    }
    if config.get("scopes"):
        result["scopes"] = config["scopes"]
    return cors_response(200, result)


def handle_auth_code(params):
    """Exchange authorization code for tokens."""
    code = params.get("code", "")
    code_verifier = params.get("code_verifier", "")

    if not code:
        return cors_response(400, {"error": "missing_code"})
    if not code_verifier:
        return cors_response(400, {"error": "missing_code_verifier"})

    pair = params.get("pair", "")
    if pair and not PAIR_CODE_RE.match(pair):
        return cors_response(400, {"error": "invalid_pair"})

    config = get_config()

    token_body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.get("redirect-uri", ""),
            "code_verifier": code_verifier,
        }
    ).encode()

    if not pair:
        return call_token_endpoint(token_body)

    # The browser never gets the tokens; they wait on the pairing for PebbleKit JS.
    status, data = fetch_tokens(token_body)
    if status != 200:
        return cors_response(status, data)
    try:
        _pairing_client().update_item(
            TableName=_pairing_table(),
            Key={"code": {"S": pair}},
            UpdateExpression="SET tokens = :t",
            ConditionExpression="attribute_exists(code) AND attribute_not_exists(tokens) AND #ttl > :now",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":t": {"S": json.dumps(data)},
                ":now": {"N": str(int(time.time()))},
            },
        )
    except _pairing_client().exceptions.ConditionalCheckFailedException:
        return cors_response(
            410, {"error": "pair_expired", "detail": "Login link expired or already used"}
        )
    return cors_response(200, {"ok": True})


def handle_refresh(params):
    """Refresh an access token."""
    refresh_token = params.get("refresh_token", "")

    if not refresh_token:
        return cors_response(400, {"error": "missing_refresh_token"})

    token_body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode()

    return call_token_endpoint(token_body)


def call_token_endpoint(body):
    status, data = fetch_tokens(body)
    return cors_response(status, data)


def fetch_tokens(body):
    """Call Volvo's token endpoint with Basic auth (secret from SSM).

    Returns (status, dict): the token payload on 200, a safe error otherwise.
    """
    config = get_config()
    client_id = config.get("client-id", "")
    client_secret = config.get("client-secret", "")
    token_url = config.get("token-endpoint", DEFAULT_TOKEN_ENDPOINT)

    credentials = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    req = urllib.request.Request(
        token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth}",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return 200, {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "token_type": data.get("token_type", "Bearer"),
                "vcc_api_key": config.get("vcc-api-key", ""),
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            err_data = json.loads(error_body)
            # Only expose safe error fields, not internal details
            err = {
                "error": err_data.get("error", "token_error"),
                "detail": err_data.get("error_description", "Token exchange failed"),
            }
        except Exception:
            err = {"error": "token_error", "detail": "Token exchange failed"}
        return e.code, err
    except urllib.error.URLError as e:
        return 502, {"error": "network_error", "detail": str(e.reason)}


# ─── Browser-login pairing ───────────────────────────────────────────────────

_dynamodb = None


def _pairing_client():
    global _dynamodb
    if _dynamodb is None:
        import boto3

        _dynamodb = boto3.client("dynamodb")
    return _dynamodb


def _pairing_table():
    return os.environ["PAIRING_TABLE"]


def _hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def handle_pair_start():
    """The code goes through the browser; the secret stays in PebbleKit JS."""
    code = secrets.token_urlsafe(16)
    secret = secrets.token_urlsafe(32)
    _pairing_client().put_item(
        TableName=_pairing_table(),
        Item={
            "code": {"S": code},
            "secret_hash": {"S": _hash_secret(secret)},
            "ttl": {"N": str(int(time.time()) + PAIR_TTL_SECONDS)},
        },
        ConditionExpression="attribute_not_exists(code)",
    )
    return cors_response(
        200, {"code": code, "secret": secret, "expires_in": PAIR_TTL_SECONDS}
    )


def handle_pair_poll(params):
    code = params.get("code", "")
    secret = params.get("secret", "")
    not_found = cors_response(404, {"error": "pair_not_found"})
    if not PAIR_CODE_RE.match(code) or not secret:
        return not_found

    item = _pairing_client().get_item(
        TableName=_pairing_table(), Key={"code": {"S": code}}, ConsistentRead=True
    ).get("Item")
    # DynamoDB TTL deletes lazily, so check expiry here too. Unknown code, wrong
    # secret and expired all look the same to the caller.
    if (
        not item
        or int(item["ttl"]["N"]) <= int(time.time())
        or not hmac.compare_digest(item["secret_hash"]["S"], _hash_secret(secret))
    ):
        return not_found
    if "tokens" not in item:
        return cors_response(202, {"status": "pending"})

    # Conditional delete, so only one concurrent poll gets the tokens.
    try:
        old = _pairing_client().delete_item(
            TableName=_pairing_table(),
            Key={"code": {"S": code}},
            ConditionExpression="attribute_exists(tokens)",
            ReturnValues="ALL_OLD",
        )
    except _pairing_client().exceptions.ConditionalCheckFailedException:
        return not_found
    return cors_response(200, json.loads(old["Attributes"]["tokens"]["S"]))


def cors_response(status_code, body):
    """Build response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": _request_origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }
