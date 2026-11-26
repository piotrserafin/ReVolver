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
    /revolver/scopes           (String)       - Space-separated OAuth scopes
    /revolver/auth-endpoint    (String)       - Volvo authorization URL (optional)
    /revolver/token-endpoint   (String)       - Volvo token URL (optional)

Environment variables:
    SSM_PREFIX     - Parameter path prefix (default: /revolver)
    PAIRING_TABLE  - DynamoDB table for browser-login pairing

Browser-login pairing: login runs in the phone's browser,
tokens reach PebbleKit JS through a short-lived pairing item:
    POST action=pair_start                -> {code, secret}  (PebbleKit JS)
    POST grant_type=authorization_code&pair=<code>
                                          -> {ok: true, confirm_code}  (browser; tokens held, never returned)
    POST action=pair_confirm&code=&confirm=
                                          -> 200 | 403 wrong code (attempts_left) | 404  (Pebble settings page)
    POST action=pair_poll&code=&secret=   -> 202 pending | 200 tokens (once, after confirm) | 404

The confirm code is shown only in the browser that did the Volvo login, and the
user types it into ReVolver settings in the Pebble app. Tokens are released only
after that, so a login started from someone else's link never reaches them.
"""

import json
import os
import re
import time
import base64
import http.client
import hashlib
import hmac
import secrets
import socket
import urllib.request
import urllib.parse
import urllib.error

DEFAULT_TOKEN_ENDPOINT = "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/token"
DEFAULT_AUTH_ENDPOINT = "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth"

PAIR_TTL_SECONDS = 600
PAIR_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# No 0/O, 1/I/L: easy to read in the browser and type in the Pebble app.
CONFIRM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CONFIRM_LENGTH = 6
CONFIRM_MAX_ATTEMPTS = 5

# Cheap checks before anything reaches Volvo, so junk requests don't spend
# the app's Volvo client credentials. Generous limits: Volvo's codes and
# tokens are far shorter. Characters: URL-safe base64, JWT dots, RFC 7636.
MAX_BODY_BYTES = 16 * 1024
TOKEN_CHARS_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")
MAX_AUTH_CODE_LENGTH = 2048
MAX_REFRESH_TOKEN_LENGTH = 8192
# RFC 7636: 43-128 characters from [A-Za-z0-9-._~]
CODE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


# Seconds; a rotated secret takes effect within this time, no cold start needed.
CONFIG_TTL_SECONDS = 300
# Without these the Lambda refuses to work instead of falling back to defaults.
REQUIRED_CONFIG = ("client-id", "client-secret", "vcc-api-key", "redirect-uri",
                   "allowed-origins", "scopes")
# Below the Lambda's 15 s timeout, so a slow Volvo gets a clean 504.
# Token calls from the Lambda take 5-7 s today (p90 5.7 s, max 6.8 s; Volvo
# itself answers in ~0.3 s), see "volvo_call" timings in the log.
VOLVO_TIMEOUT_SECONDS = 12

_config = {}
_config_expires = 0.0


class ConfigError(Exception):
    pass


def log(level, event, **fields):
    """One JSON line per event. Never pass request bodies, tokens or secrets."""
    print(json.dumps({"level": level, "event": event, **fields}))


def get_config():
    """Load config from SSM Parameter Store, cached for CONFIG_TTL_SECONDS."""
    global _config, _config_expires
    if _config and time.time() < _config_expires:
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

    config = {}
    for param in resp["Parameters"]:
        key = param["Name"].split("/")[-1]  # e.g. "client-id"
        config[key] = param["Value"]

    missing = [k for k in REQUIRED_CONFIG if not config.get(k)]
    if missing:
        # Names only, never values
        log("error", "config_missing", params=missing)
        raise ConfigError(", ".join(missing))

    _config = config
    _config_expires = time.time() + CONFIG_TTL_SECONDS
    return _config


# Current request origin and kind (set per invocation; kind is for logs only)
_request_origin = ""
_request_kind = ""


# ─── Handler ─────────────────────────────────────────────────────────────────


def lambda_handler(event, context):
    """Handle config, token exchange, and token refresh requests."""
    global _request_kind
    _request_kind = ""
    try:
        return _handle(event)
    except ConfigError:
        return _plain_error(503, "not_configured")
    except Exception as e:
        # Type and request kind only: messages and tracebacks may contain tokens
        log("error", "unhandled", error=type(e).__name__, kind=_request_kind)
        return _plain_error(500, "internal_error")


def _plain_error(status, error):
    """No CORS headers: the origin may not have been checked yet."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": error}),
    }


def _handle(event):
    """Internal request handler."""
    global _request_origin, _request_kind
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")

    # Verify request origin
    origin = (event.get("headers") or {}).get("origin", "")
    config = get_config()
    allowed_origins = [o.strip() for o in config["allowed-origins"].split(",")]

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
        body = event.get("body") or ""
        if len(body) > 2 * MAX_BODY_BYTES:  # room for base64
            return cors_response(413, {"error": "request_too_large"})
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        params = dict(urllib.parse.parse_qsl(body))
    except Exception:
        return cors_response(400, {"error": "invalid_request"})

    action = params.get("action", "")
    _request_kind = action or params.get("grant_type", "")[:32]
    if action == "pair_start":
        return handle_pair_start()
    if action == "pair_poll":
        return handle_pair_poll(params)
    if action == "pair_confirm":
        return handle_pair_confirm(params)

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
    if len(code) > MAX_AUTH_CODE_LENGTH or not TOKEN_CHARS_RE.match(code):
        return cors_response(400, {"error": "invalid_code"})
    if not CODE_VERIFIER_RE.match(code_verifier):
        return cors_response(400, {"error": "invalid_code_verifier"})

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

    # The browser never gets the tokens; they wait on the pairing for PebbleKit JS
    # until the user confirms with the code shown in this browser.
    expired = cors_response(
        410, {"error": "pair_expired", "detail": "Login link expired or already used"}
    )
    # Check first, so a dead or made-up pairing doesn't redeem the code with Volvo.
    item = _get_pairing(pair)
    if not _pairing_live(item) or "tokens" in item:
        return expired

    status, data = fetch_tokens(token_body)
    if status != 200:
        return cors_response(status, data)
    confirm = new_confirm_code()
    try:
        _pairing_client().update_item(
            TableName=_pairing_table(),
            Key={"code": {"S": pair}},
            UpdateExpression="SET tokens = :t, confirm_hash = :c, attempts = :zero",
            ConditionExpression="attribute_exists(code) AND attribute_not_exists(tokens) AND #ttl > :now",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":t": {"S": json.dumps(data)},
                ":c": {"S": _hash_secret(confirm)},
                ":zero": {"N": "0"},
                ":now": {"N": str(int(time.time()))},
            },
        )
    except _pairing_client().exceptions.ConditionalCheckFailedException:
        return expired
    return cors_response(200, {"ok": True, "confirm_code": confirm})


def handle_refresh(params):
    """Refresh an access token."""
    refresh_token = params.get("refresh_token", "")

    if not refresh_token:
        return cors_response(400, {"error": "missing_refresh_token"})
    if len(refresh_token) > MAX_REFRESH_TOKEN_LENGTH or not TOKEN_CHARS_RE.match(refresh_token):
        return cors_response(400, {"error": "invalid_refresh_token"})

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


# ─── Volvo call timing ───────────────────────────────────────────────────────
# Phases of the last Volvo call (ms), logged as "volvo_call". Measured inside
# the one connection urllib makes, so no extra DNS lookups or requests.
_timing = {}


def _ms(start):
    return round((time.monotonic() - start) * 1000)


class _TimedHTTPSConnection(http.client.HTTPSConnection):
    """Same steps as socket.create_connection + TLS, with each one timed."""

    def connect(self):
        t = time.monotonic()
        infos = socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM)
        _timing["dns_ms"] = _ms(t)
        _timing["addrs"] = "".join("6" if i[0] == socket.AF_INET6 else "4" for i in infos)
        sock, err, failed = None, None, []
        t = time.monotonic()
        for family, socktype, proto, _, addr in infos:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(self.timeout)
            try:
                sock.connect(addr)
                break
            except OSError as e:
                failed.append(("6" if family == socket.AF_INET6 else "4") + ":" + type(e).__name__)
                sock.close()
                err, sock = e, None
        _timing["connect_ms"] = _ms(t)
        if failed:
            _timing["connect_failed"] = failed
        if sock is None:
            raise err or OSError("no address")
        t = time.monotonic()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        _timing["tls_ms"] = _ms(t)


class _TimedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_TimedHTTPSConnection, req, context=self._context)


_opener = urllib.request.build_opener(_TimedHTTPSHandler())


def _open(req):
    return _opener.open(req, timeout=VOLVO_TIMEOUT_SECONDS)


def fetch_tokens(body):
    """Call Volvo, then log how long each phase took ("volvo_call")."""
    _timing.clear()
    start = time.monotonic()
    try:
        return _fetch_tokens(body)
    finally:
        log("info", "volvo_call", kind=_request_kind, total_ms=_ms(start), **_timing)


def _fetch_tokens(body):
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
        with _open(req) as resp:
            _timing["status"] = resp.status
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
        # Volvo's error code is safe to log (e.g. invalid_grant); the description isn't needed.
        _timing["status"] = e.code
        log("warn", "volvo_error", status=e.code, error=str(err["error"])[:64], kind=_request_kind)
        return e.code, err
    except (TimeoutError, socket.timeout):
        log("warn", "volvo_timeout", kind=_request_kind)
        return 504, {"error": "timeout", "detail": "Volvo did not answer in time"}
    except urllib.error.URLError as e:
        # The reason (DNS, socket detail) goes to the log, not to the client.
        log("warn", "volvo_network_error", error=type(e.reason).__name__, kind=_request_kind)
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            return 504, {"error": "timeout", "detail": "Volvo did not answer in time"}
        return 502, {"error": "network_error", "detail": "Could not reach Volvo"}


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


def new_confirm_code():
    return "".join(secrets.choice(CONFIRM_ALPHABET) for _ in range(CONFIRM_LENGTH))


def normalize_confirm(value):
    """Accept what people type: lower case, spaces, a dash in the middle."""
    return "".join(ch for ch in value.upper() if ch not in " -")


def _get_pairing(code):
    return (
        _pairing_client()
        .get_item(TableName=_pairing_table(), Key={"code": {"S": code}}, ConsistentRead=True)
        .get("Item")
    )


def _pairing_live(item):
    # DynamoDB TTL deletes lazily, so check expiry here too.
    return bool(item) and int(item["ttl"]["N"]) > int(time.time())


def handle_pair_confirm(params):
    """The user types the code from the browser into ReVolver settings (Pebble app)."""
    code = params.get("code", "")
    confirm = normalize_confirm(params.get("confirm", ""))
    not_found = cors_response(404, {"error": "pair_not_found"})
    if not PAIR_CODE_RE.match(code):
        return not_found
    if len(confirm) != CONFIRM_LENGTH or any(ch not in CONFIRM_ALPHABET for ch in confirm):
        return cors_response(400, {"error": "invalid_confirm"})

    item = _get_pairing(code)
    if not _pairing_live(item) or "confirm_hash" not in item:
        return not_found
    if item.get("confirmed", {}).get("BOOL"):
        return cors_response(200, {"ok": True})

    if hmac.compare_digest(item["confirm_hash"]["S"], _hash_secret(confirm)):
        _pairing_client().update_item(
            TableName=_pairing_table(),
            Key={"code": {"S": code}},
            UpdateExpression="SET confirmed = :t",
            ConditionExpression="attribute_exists(tokens)",
            ExpressionAttributeValues={":t": {"BOOL": True}},
        )
        return cors_response(200, {"ok": True})

    # Wrong code: count it; the last allowed miss deletes the pairing (and the tokens).
    try:
        attrs = _pairing_client().update_item(
            TableName=_pairing_table(),
            Key={"code": {"S": code}},
            UpdateExpression="ADD attempts :one",
            ConditionExpression="attribute_exists(tokens) AND attempts < :max",
            ExpressionAttributeValues={
                ":one": {"N": "1"},
                ":max": {"N": str(CONFIRM_MAX_ATTEMPTS)},
            },
            ReturnValues="UPDATED_NEW",
        )["Attributes"]
        left = CONFIRM_MAX_ATTEMPTS - int(attrs["attempts"]["N"])
    except _pairing_client().exceptions.ConditionalCheckFailedException:
        left = 0
    if left <= 0:
        _pairing_client().delete_item(TableName=_pairing_table(), Key={"code": {"S": code}})
        return not_found
    return cors_response(403, {"error": "wrong_code", "attempts_left": left})


def handle_pair_poll(params):
    code = params.get("code", "")
    secret = params.get("secret", "")
    not_found = cors_response(404, {"error": "pair_not_found"})
    if not PAIR_CODE_RE.match(code) or not secret:
        return not_found

    item = _get_pairing(code)
    # Unknown code, wrong secret and expired all look the same to the caller.
    if not _pairing_live(item) or not hmac.compare_digest(
        item["secret_hash"]["S"], _hash_secret(secret)
    ):
        return not_found
    if "tokens" not in item:
        return cors_response(202, {"status": "pending"})
    if not item.get("confirmed", {}).get("BOOL"):
        # Logged in, waiting for the code from the browser (older apps treat 202 as pending)
        return cors_response(202, {"status": "confirm"})

    # Conditional delete, so only one concurrent poll gets the tokens.
    try:
        old = _pairing_client().delete_item(
            TableName=_pairing_table(),
            Key={"code": {"S": code}},
            ConditionExpression="attribute_exists(tokens) AND confirmed = :t",
            ExpressionAttributeValues={":t": {"BOOL": True}},
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
