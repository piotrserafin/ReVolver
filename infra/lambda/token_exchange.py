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
    SSM_PREFIX  - Parameter path prefix (default: /revolver)
"""

import json
import os
import base64
import urllib.request
import urllib.parse
import urllib.error

DEFAULT_TOKEN_ENDPOINT = "https://volvoid.eu.volvocars.com/as/token.oauth2"
DEFAULT_ALLOWED_ORIGINS = "https://piotrserafin.github.io,https://piotrserafin.dev"
DEFAULT_AUTH_ENDPOINT = "https://volvoid.eu.volvocars.com/as/authorization.oauth2"


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
    except Exception as e:
        return cors_response(400, {"error": "invalid_request", "detail": str(e)})

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

    config = get_config()

    token_body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.get("redirect-uri", ""),
            "code_verifier": code_verifier,
        }
    ).encode()

    return call_token_endpoint(token_body)


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
    """Call Volvo's token endpoint with Basic auth (secret from SSM)."""
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
            return cors_response(
                200,
                {
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                    "expires_in": data.get("expires_in"),
                    "token_type": data.get("token_type", "Bearer"),
                    "vcc_api_key": config.get("vcc-api-key", ""),
                },
            )
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
        return cors_response(e.code, err)
    except urllib.error.URLError as e:
        return cors_response(502, {"error": "network_error", "detail": str(e.reason)})


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
