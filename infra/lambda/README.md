# ReVolver Token Exchange Lambda

## Overview

AWS Lambda function that acts as a secure proxy between the Pebble app and Volvo ID's OAuth2 token endpoint. Its primary purpose is to keep the `client_secret` and `vcc-api-key` server-side — they never appear in client code, the app binary, or over Bluetooth. The Lambda is exposed via a **Function URL** (no API Gateway needed).

## Why Lambda Is Required

Volvo's OAuth implementation requires **both PKCE AND `client_secret`** for token exchange. This is unusual — most providers use one or the other:

| Provider Style | PKCE | client_secret | Server needed? |
|---|---|---|---|
| Public client (e.g., mobile apps) | ✅ | ❌ | No |
| Confidential client (e.g., backend) | ❌ | ✅ | Yes |
| **Volvo** | ✅ | ✅ | **Yes** |

If Volvo supported PKCE-only (public client flow), the static ReVolverAuth page could call the token endpoint directly — no Lambda needed. But they don't.

The `client_secret` can't live in:
- ❌ ReVolverAuth HTML (public GitHub repo, viewable source)
- ❌ Pebble app binary (extractable from .pbw)
- ❌ PebbleKit JS (visible in phone app storage)
- ✅ **Lambda only** (SSM Parameter Store, never exposed)

Lambda exists for one reason: **to add `client_secret` to the token exchange request**. Everything else (PKCE generation, redirects, user login) happens client-side. Same for refresh — Volvo requires `client_secret` on the refresh endpoint too.

## What It Does

### 1. GET — Return OAuth Config

Returns public OAuth configuration to the auth frontend page. No secrets exposed.

```
ReVolverAuth page ──GET──► Lambda
                          │
                          ├── Read from SSM: client-id, redirect-uri, scopes, auth-endpoint
                          │
                   ◄──────┤  {client_id, redirect_uri, scopes, auth_endpoint}
```

**Input:** None (just a GET request)

**Output:**

```json
{
  "client_id": "abc123",
  "redirect_uri": "https://piotrserafin.github.io/ReVolverAuth/",
  "scopes": "openid conve:lock conve:unlock ...",
  "auth_endpoint": "https://volvoid.eu.volvocars.com/as/authorization.oauth2"
}
```

### 2. POST — Token Exchange (authorization_code)

Exchanges an OAuth authorization code + PKCE verifier for access/refresh tokens. Called by the auth frontend after user logs in with Volvo ID.

```
ReVolverAuth page ──POST──► Lambda ──POST──► Volvo token endpoint
                           │                │
                           │ Adds:          │
                           │ - client_secret│
                           │   (Basic auth) │
                           │                │
                    ◄──────┤  {tokens +     │◄── {access_token,
                           │   vcc_api_key} │     refresh_token,
                           │                │     expires_in}
```

**Input:** (application/x-www-form-urlencoded)

```
grant_type=authorization_code
code=<auth_code_from_volvo>
code_verifier=<pkce_verifier>
```

**Output:**

```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "Na2ALG...",
  "expires_in": 300,
  "token_type": "Bearer",
  "vcc_api_key": "abc123..."
}
```

**What Lambda adds:**

- `client_secret` via HTTP Basic auth header (from SSM)
- `redirect_uri` in the request body (from SSM)
- `vcc_api_key` in the response (from SSM)

### 3. POST — Token Refresh (refresh_token)

Refreshes an expired access token. Called by PebbleKit JS directly (no webview needed).

```
PebbleKit JS ──POST──► Lambda ──POST──► Volvo token endpoint
                       │                │
                       │ Adds:          │
                       │ - client_secret│
                       │                │
                ◄──────┤  {new tokens + │◄── {new access_token,
                       │   vcc_api_key} │     new refresh_token,
                       │                │     expires_in}
```

**Input:** (application/x-www-form-urlencoded)

```
grant_type=refresh_token
refresh_token=<current_refresh_token>
```

**Output:** Same format as token exchange above (new tokens + vcc_api_key).

**Important:** Volvo rotates refresh tokens — each one is single-use. The old token is invalidated after a successful refresh.

### 4. OPTIONS — CORS Preflight

Responds to browser CORS preflight requests with appropriate headers.

**Input:** OPTIONS request with Origin header

**Output:** 200 with CORS headers

## Sequence Diagram — Full OAuth Flow (including Volvo login)

```
┌────────────────┐     ┌────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ ReVolverAuth   │     │ Lambda         │     │ Volvo ID         │     │ Volvo Token      │
│ (browser)      │     │                │     │ (login page)     │     │ Endpoint         │
└───────┬────────┘     └───────┬────────┘     └────────┬─────────┘     └────────┬─────────┘
        │                      │                       │                        │
        │ GET /                │                       │                        │
        │─────────────────────>│                       │                        │
        │                      │                       │                        │
        │ {client_id,          │                       │                        │
        │  redirect_uri,       │                       │                        │
        │  scopes,             │                       │                        │
        │  auth_endpoint}      │                       │                        │
        │<─────────────────────┤                       │                        │
        │                      │                       │                        │
        │ Generate PKCE:       │                       │                        │
        │  code_verifier =     │                       │                        │
        │    random(43 chars)  │                       │                        │
        │  code_challenge =    │                       │                        │
        │    BASE64URL(SHA256( │                       │                        │
        │      code_verifier)) │                       │                        │
        │  Store verifier in   │                       │                        │
        │    sessionStorage    │                       │                        │
        │                      │                       │                        │
        │ Redirect ───────────────────────────────────>│                        │
        │ GET /as/authorization.oauth2                 │                        │
        │   ?client_id=abc123                          │                        │
        │   &redirect_uri=https://...ReVolverAuth/     │                        │
        │   &response_type=code                        │                        │
        │   &scope=openid conve:lock conve:unlock ...  │                        │
        │   &code_challenge=<base64url>                │                        │
        │   &code_challenge_method=S256                │                        │
        │   &state=<random>                            │                        │
        │                      │                       │                        │
        │                      │              User sees Volvo ID                │
        │                      │              login page. Enters                │
        │                      │              email + password.                 │
        │                      │                       │                        │
        │ Redirect back ◄──────────────────────────────┤                        │
        │ GET https://...ReVolverAuth/                 │                        │
        │   ?code=AUTH_CODE_ABC                        │                        │
        │   &state=<random>                            │                        │
        │                      │                       │                        │
        │ POST /               │                       │                        │
        │ grant_type=          │                       │                        │
        │ authorization_code   │                       │                        │
        │ code=AUTH_CODE_ABC   │                       │                        │
        │ code_verifier=XYZ    │                       │                        │
        │─────────────────────>│                       │                        │
        │                      │                       │                        │
        │                      │ POST /as/token.oauth2 │                        │
        │                      │ Authorization: Basic  │                        │
        │                      │   base64(id:secret)   │                        │
        │                      │ Body:                 │                        │
        │                      │   grant_type=         │                        │
        │                      │   authorization_code  │                        │
        │                      │   code=AUTH_CODE_ABC  │                        │
        │                      │   code_verifier=XYZ   │                        │
        │                      │   redirect_uri=...    │                        │
        │                      │───────────────────────────────────────────────>│
        │                      │                       │                        │
        │                      │                       │  Volvo validates:      │
        │                      │                       │  - code (single-use)   │
        │                      │                       │  - verifier vs challenge
        │                      │                       │  - client_secret       │
        │                      │                       │  - redirect_uri match  │
        │                      │                       │                        │
        │                      │                       │  200 {access_token,    │
        │                      │                       │       refresh_token,   │
        │                      │                       │       expires_in: 300} │
        │                      │<───────────────────────────────────────────────┤
        │                      │                       │                        │
        │ 200 {access_token,   │                       │                        │
        │      refresh_token,  │                       │                        │
        │      expires_in,     │                       │                        │
        │      token_type,     │                       │                        │
        │      vcc_api_key}    │                       │                        │
        │<─────────────────────┤                       │                        │
        │                      │                       │                        │
        │ pebblejs://close#    │                       │                        │
        │ {ACCESS_TOKEN,       │                       │                        │
        │  REFRESH_TOKEN,      │                       │                        │
        │  EXPIRES_IN,         │                       │                        │
        │  VCC_API_KEY}        │                       │                        │
        │──► Pebble app closes │                       │                        │
        │    webview           │                       │                        │
        │                      │                       │                        │
```

### PKCE (Proof Key for Code Exchange)

PKCE prevents authorization code interception — even if an attacker captures the `code` from the redirect URL, they can't exchange it for tokens without the original `code_verifier`.

The PKCE pair is generated by the **ReVolverAuth page** (JavaScript running in the phone's webview), not by Lambda or the watch.

```
ReVolverAuth — the OAuth client (JavaScript running in the phone's webview) — generates:
  verifier  = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  (random, stays in sessionStorage)
  challenge = BASE64URL(SHA256(verifier))
            = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"   (hash, sent to Volvo)

Step 1 — Login redirect:
  &code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM  (only the hash travels)
  &code_challenge_method=S256

Step 2 — Token exchange (via Lambda):
  &code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk  (original, from sessionStorage)

Volvo checks:
  SHA256("dBjftJ...") == "E9Melh..." → ✅ match → issue tokens
```

- **verifier** — never leaves the browser until the POST to Lambda (same origin)
- **challenge** — only a hash, useless without the original verifier
- **code** — single-use, can't be exchanged without both verifier AND client_secret

## Sequence Diagram — Token Exchange

```
┌────────────────┐     ┌────────────────┐     ┌──────────────────┐
│ ReVolverAuth   │     │ Lambda         │     │ Volvo Token      │
│ (browser)      │     │                │     │ Endpoint         │
└───────┬────────┘     └───────┬────────┘     └────────┬─────────┘
        │                      │                       │
        │ POST /               │                       │
        │ grant_type=          │                       │
        │ authorization_code   │                       │
        │ code=ABC             │                       │
        │ code_verifier=XYZ    │                       │
        │─────────────────────>│                       │
        │                      │                       │
        │                      │ Read SSM:             │
        │                      │ - client-id           │
        │                      │ - client-secret       │
        │                      │ - redirect-uri        │
        │                      │ - vcc-api-key         │
        │                      │                       │
        │                      │ POST /as/token.oauth2 │
        │                      │ Authorization: Basic  │
        │                      │   base64(id:secret)   │
        │                      │ Body:                 │
        │                      │   grant_type=         │
        │                      │   authorization_code  │
        │                      │   code=ABC            │
        │                      │   code_verifier=XYZ   │
        │                      │   redirect_uri=...    │
        │                      │──────────────────────>│
        │                      │                       │
        │                      │ 200 {access_token,    │
        │                      │      refresh_token,   │
        │                      │      expires_in}      │
        │                      │<──────────────────────┤
        │                      │                       │
        │ 200 {access_token,   │                       │
        │      refresh_token,  │                       │
        │      expires_in,     │                       │
        │      token_type,     │                       │
        │      vcc_api_key}    │                       │
        │<─────────────────────┤                       │
        │                      │                       │
```

## Sequence Diagram — Token Refresh

```
┌────────────────┐     ┌────────────────┐     ┌──────────────────┐
│ PebbleKit JS   │     │ Lambda         │     │ Volvo Token      │
│ (on phone)     │     │                │     │ Endpoint         │
└───────┬────────┘     └───────┬────────┘     └────────┬─────────┘
        │                      │                       │
        │ POST /               │                       │
        │ grant_type=          │                       │
        │ refresh_token        │                       │
        │ refresh_token=RT1    │                       │
        │─────────────────────>│                       │
        │                      │                       │
        │                      │ POST /as/token.oauth2 │
        │                      │ Authorization: Basic  │
        │                      │ Body:                 │
        │                      │   grant_type=         │
        │                      │   refresh_token       │
        │                      │   refresh_token=RT1   │
        │                      │──────────────────────>│
        │                      │                       │
        │                      │ 200 {new access_token,│
        │                      │      RT2 (new),       │
        │                      │      expires_in}      │
        │                      │<──────────────────────┤
        │                      │                       │
        │ 200 {access_token,   │  RT1 is now invalid   │
        │      refresh_token   │                       │
        │      (RT2),          │                       │
        │      expires_in,     │                       │
        │      vcc_api_key}    │                       │
        │<─────────────────────┤                       │
        │                      │                       │
```

## SSM Parameters

| Parameter                   | Type         | Required | Description                                |
| --------------------------- | ------------ | -------- | ------------------------------------------ |
| `/revolver/client-id`       | SecureString | ✅       | Volvo application client ID                |
| `/revolver/client-secret`   | SecureString | ✅       | Volvo application client secret            |
| `/revolver/vcc-api-key`     | SecureString | ✅       | Volvo Connected Cars API key               |
| `/revolver/redirect-uri`    | String       | ✅       | OAuth redirect URI                         |
| `/revolver/allowed-origins` | String       | ✅       | Comma-separated allowed CORS origins       |
| `/revolver/scopes`          | String       | Optional | Space-separated OAuth scopes (has default) |
| `/revolver/auth-endpoint`   | String       | Optional | Volvo auth URL (has default)               |
| `/revolver/token-endpoint`  | String       | Optional | Volvo token URL (has default)              |

### Create Parameters

```bash
aws ssm put-parameter \
  --name /revolver/client-id \
  --value "your-volvo-client-id" \
  --type SecureString

aws ssm put-parameter \
  --name /revolver/client-secret \
  --value "your-volvo-client-secret" \
  --type SecureString

aws ssm put-parameter \
  --name /revolver/vcc-api-key \
  --value "your-volvo-vcc-api-key" \
  --type SecureString

aws ssm put-parameter \
  --name /revolver/redirect-uri \
  --value "https://piotrserafin.github.io/ReVolverAuth/" \
  --type String

aws ssm put-parameter \
  --name /revolver/allowed-origins \
  --value "https://piotrserafin.github.io,https://piotrserafin.dev" \
  --type String
```

## Deploy

```bash
cd infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk deploy
```

## Error Handling

| Scenario               | Lambda Response                                            |
| ---------------------- | ---------------------------------------------------------- |
| Invalid origin         | 403 `{"error": "forbidden"}`                               |
| Missing code           | 400 `{"error": "missing_code"}`                            |
| Missing verifier       | 400 `{"error": "missing_code_verifier"}`                   |
| Missing refresh_token  | 400 `{"error": "missing_refresh_token"}`                   |
| Unsupported grant_type | 400 `{"error": "unsupported_grant_type"}`                  |
| Volvo returns error    | Volvo's status code + sanitized error (no raw body leaked) |
| Volvo unreachable      | 502 `{"error": "network_error"}`                           |

## Security

| Concern                | Solution                                                                   |
| ---------------------- | -------------------------------------------------------------------------- |
| client_secret exposure | Never in code/response — only used in Basic auth header to Volvo           |
| vcc_api_key exposure   | Returned to client in token response (needed for direct API calls)         |
| Origin validation      | Checked against SSM `allowed-origins` list                                 |
| Error leaking          | Volvo error bodies sanitized — only `error` and `error_description` passed |
| Unhandled exceptions   | Top-level try/catch returns generic 500 — no secrets/tokens in CloudWatch  |
| SSM access             | IAM scoped to `/revolver/*` parameters only                                |
| KMS decryption         | Restricted to SSM service context with parameter ARN condition             |
| Config caching         | SSM values cached after cold start (no per-request SSM calls)              |

## Cost

**Free** for personal use:

- Lambda: 1M free requests/month
- Function URL: no additional cost
- SSM Parameter Store: free for standard parameters
- KMS: free for SSM default key (`aws/ssm`)

## Rotate Secrets

Update SSM parameter — no redeploy needed:

```bash
aws ssm put-parameter \
  --name /revolver/client-secret \
  --value "new-secret" \
  --type SecureString \
  --overwrite
```

Force Lambda cold start to pick up new values:

```bash
aws lambda update-function-configuration \
  --function-name ReVolverAuthStack-token-exchange \
  --description "reload $(date +%s)"
```
