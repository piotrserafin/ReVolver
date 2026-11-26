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
  "auth_endpoint": "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth"
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

### 4. POST — Browser-Login Pairing

The Core Devices Pebble app on Android injects a script into watchapp settings pages that deletes `window.customElements`. Volvo's login page calls `customElements.get()` while loading, crashes, and stays blank ([coredevices/mobileapp#507](https://github.com/coredevices/mobileapp/issues/507)). So the login runs in the phone's browser instead (opened with `Pebble.openUrl`), and the browser can't pass tokens back to PebbleKit JS. The Lambda bridges the two with a pairing item in DynamoDB (`<stack>-pairing`, TTL 10 min): the browser leaves the tokens there, PebbleKit JS collects them with a secret only it holds.

```
PebbleKit JS ──action=pair_start──► Lambda ── {code, secret}       (sha256(secret) stored)
Browser      ──authorization_code + pair=<code>──► Lambda ──► Volvo
                                                   tokens held on the item; browser gets {"ok": true, "confirm_code"}
Settings page ──action=pair_confirm + code + confirm_code──► Lambda   (user types the code from the browser)
PebbleKit JS ──action=pair_poll + code + secret──► Lambda ── 202 pending/confirm | 200 tokens (item deleted)
```

**Input:** (application/x-www-form-urlencoded)

```
action=pair_start
action=pair_poll&code=<code>&secret=<secret>
action=pair_confirm&code=<code>&confirm=<confirm_code>
grant_type=authorization_code&code=...&code_verifier=...&pair=<code>
```

**Output:**

| Call | Response |
|---|---|
| `pair_start` | 200 `{"code", "secret", "expires_in": 600}` |
| `pair_poll` | 202 `{"status": "pending"}` (no login yet) or `{"status": "confirm"}` (waiting for the code), 200 = same body as token exchange (once, only after `pair_confirm`), 404 `{"error": "pair_not_found"}` (unknown, wrong secret or expired) |
| exchange with `pair` | 200 `{"ok": true, "confirm_code": "K7P2QX"}` (6 characters, no 0/O/1/I/L; only its hash is stored), 410 `{"error": "pair_expired"}` (expired or already used; checked before the code is redeemed with Volvo) |
| `pair_confirm` | 200 `{"ok": true}`, 403 `{"error": "wrong_code", "attempts_left"}`, 404 after the 5th wrong code (pairing and tokens deleted) or if unknown / expired / no login yet, 400 `{"error": "invalid_confirm"}` (wrong format; accepts lower case, spaces and a dash) |

Tests: `python3 -m unittest discover -s infra/lambda -p 'test_*.py'` (pairing and input checks; fake DynamoDB, no AWS; runs in CI).

### 5. OPTIONS — CORS Preflight

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
        │ GET <auth endpoint>                          │                        │
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
        │                      │ POST <token endpoint> │                        │
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
        │                      │ POST <token endpoint> │
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
        │                      │ POST <token endpoint> │
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
| `/revolver/scopes`          | String       | ✅       | Space-separated OAuth scopes               |
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

Merging to `main` with changes under `infra/**` runs `cdk deploy` (prod) automatically via `.github/workflows/deploy-lambda.yml`.

## Limits and Alarms

The Function URL is public: it ships in every `.pbw`. These cap what a flood can cost and keep it from using up the Volvo client ID.

- **Concurrency cap:** the account's Lambda limit is 10 in total (prod and dev together), so above 10 concurrent requests callers get 429. No reserved concurrency: AWS keeps 10 unreserved, so reserving any fails the deploy. If the quota is ever raised, reserve ~10 for prod in `revolver_auth_stack.py`.
- **Input checks before Volvo:** body ≤ 16 KB (413), `code` ≤ 2048 and `refresh_token` ≤ 8192 characters from `[A-Za-z0-9._~+/=-]`, `code_verifier` per RFC 7636 (43–128 characters). Anything else gets a 400 without a Volvo call.
- **CloudWatch alarms** → SNS topic `<stack>-alarms`:
  - `<stack>-throttles`: any throttle in 5 min (the cap was hit).
  - `<stack>-invocations`: more than 1000 (prod) / 200 (dev) requests in an hour.
  - `<stack>-handler-errors`: the handler logged `"level": "error"` (unhandled exception or missing SSM config). The handler catches every exception, so Lambda's own Errors metric stays 0.

### Logs

Log group `/revolver/<stack>/token-exchange`, kept 30 days. One JSON line per event, never request bodies, tokens or secrets:

| Event | Level | Fields |
|-------|-------|--------|
| `unhandled` | error | exception type, request kind (`pair_start`, `refresh_token`, …) |
| `config_missing` | error | names of the missing SSM parameters |
| `volvo_error` | warn | HTTP status, Volvo's error code (e.g. `invalid_grant`), request kind |
| `volvo_timeout`, `volvo_network_error` | warn | exception type, request kind |
| `volvo_call` | info | after every Volvo token call: `total_ms`, `dns_ms`, `connect_ms`, `tls_ms`, `addrs` (address families in DNS order, e.g. `4466`), `connect_failed` (family + error), `status` |

Find slow phases:

```bash
aws logs filter-log-events --log-group-name /revolver/ReVolverAuthStack/token-exchange \
  --filter-pattern '{ $.event = "volvo_call" }' --query 'events[].message' --output text
```

The old `/aws/lambda/<function>` log groups (no retention) are no longer written to; delete them once the new group has logs.

### Get alarm emails (once per stack)

The address is added by hand, so it is not in the repo or the CloudFormation template:

```bash
TOPIC=$(aws cloudformation describe-stacks --stack-name ReVolverAuthStack \
  --query "Stacks[0].Outputs[?OutputKey=='AlarmTopicArn'].OutputValue" --output text)
aws sns subscribe --topic-arn "$TOPIC" --protocol email --notification-endpoint you@example.com
```

Click the link in the confirmation email. Redeploys keep the subscription.

### Budget (once per AWS account)

Not in CDK, because a budget covers the whole account. Billing → Budgets → Create budget → "Monthly cost budget", e.g. $5, email alerts at 80% actual and 100% forecasted.

## Dev Stack

A separate stack for development, with its own Volvo application (unpublished), SSM prefix and Function URL. Prod is untouched.

| | Prod | Dev |
|---|---|---|
| Deploy | `cdk deploy` (or CI on merge) | `cdk deploy -c stage=dev` (manual only) |
| Stack | `ReVolverAuthStack` | `ReVolverAuthStack-dev` |
| SSM prefix | `/revolver` | `/revolver-dev` |
| Function URL | `https://tpl5qhrn75bxzps77pdqllhxuy0mckgw.lambda-url.eu-central-1.on.aws/` | `https://ckcflhkgzt3p6lsxad5uvxom740fkwbr.lambda-url.eu-central-1.on.aws/` |
| Auth page | `ReVolverAuth/` (`deploy-auth.yml`, push to `main`) | `ReVolverAuth-dev/` (`deploy-auth-dev.yml`, push to any other branch) |
| Watch app build | `pebble build` | `REVOLVER_ENV=dev pebble build` |

The dev prefix is `/revolver-dev`, not `/revolver/dev`: the prod policy grants `parameter/revolver/*`, which would let prod read dev secrets.

Setup (one time):

```bash
cd infra
cdk deploy -c stage=dev                      # outputs TokenExchangeUrl

aws ssm put-parameter --name /revolver-dev/client-id     --type SecureString --value "..."
aws ssm put-parameter --name /revolver-dev/client-secret --type SecureString --value "..."
aws ssm put-parameter --name /revolver-dev/vcc-api-key   --type SecureString --value "..."
aws ssm put-parameter --name /revolver-dev/redirect-uri    --type String --value "https://piotrserafin.github.io/ReVolverAuth-dev/"
aws ssm put-parameter --name /revolver-dev/allowed-origins --type String --value "https://piotrserafin.github.io,https://piotrserafin.dev"
aws ssm put-parameter --name /revolver-dev/scopes          --type String --value "openid conve:... energy:..."
# Optional (the Lambda defaults are already Keycloak):
aws ssm put-parameter --name /revolver-dev/auth-endpoint  --type String --value "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth"
aws ssm put-parameter --name /revolver-dev/token-endpoint --type String --value "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/token"
```

- `allowed-origins` needs **both** origins: GitHub Pages redirects `piotrserafin.github.io` to the custom domain `piotrserafin.dev`, so the browser calls from `.dev`. A missing origin shows up as a CORS error (`Access-Control-Allow-Origin` header contains the invalid value '').
- `scopes` is required: the auth page rejects a config without it. Dev and prod use the same 28 scopes (see `doc/scopes.md`); every scope must also be enabled on the Volvo app, or authorize fails with `invalid_scope`. Don't add `offline_access`: Keycloak rejects it.
- Until all required parameters exist the Lambda answers 503 `not_configured` (and logs which names are missing). It rechecks SSM at most every 5 minutes.
- When not in use: `cdk destroy -c stage=dev`. The SSM parameters are kept; a redeploy creates a **new** Function URL, which must then be updated in `wscript`, `.github/workflows/deploy-auth-dev.yml` (`DEV_LAMBDA_URL`), `auth/diag.html` and `package.json` (`usesPermissions`, needs a new app release).

## Error Handling

| Scenario               | Lambda Response                                            |
| ---------------------- | ---------------------------------------------------------- |
| Invalid origin         | 403 `{"error": "forbidden"}`                               |
| Missing code           | 400 `{"error": "missing_code"}`                            |
| Missing verifier       | 400 `{"error": "missing_code_verifier"}`                   |
| Missing refresh_token  | 400 `{"error": "missing_refresh_token"}`                   |
| Unsupported grant_type | 400 `{"error": "unsupported_grant_type"}`                  |
| Malformed `pair`       | 400 `{"error": "invalid_pair"}`                            |
| Malformed code / verifier / refresh_token | 400 `{"error": "invalid_code"}` / `invalid_code_verifier` / `invalid_refresh_token` (no Volvo call) |
| Body over 16 KB        | 413 `{"error": "request_too_large"}`                       |
| Over the concurrency cap | 429 (from AWS, before the handler runs)                  |
| Pairing expired / used | 410 `{"error": "pair_expired"}` (exchange), 404 `{"error": "pair_not_found"}` (poll) |
| Volvo returns error    | Volvo's status code + sanitized error (no raw body leaked) |
| Volvo unreachable      | 502 `{"error": "network_error"}` (details only in the log) |
| Volvo slower than 12 s | 504 `{"error": "timeout"}` (Lambda timeout is 15 s)        |
| Required SSM parameter missing | 503 `{"error": "not_configured"}`                  |

## Security

| Concern                | Solution                                                                   |
| ---------------------- | -------------------------------------------------------------------------- |
| client_secret exposure | Never in code/response — only used in Basic auth header to Volvo           |
| vcc_api_key exposure   | Returned to client in token response (needed for direct API calls)         |
| Origin validation      | Checked against SSM `allowed-origins` list                                 |
| Error leaking          | Volvo error bodies sanitized — only `error` and `error_description` passed |
| Unhandled exceptions   | Top-level try/catch returns generic 500; only the exception type is logged (no messages, tracebacks or tokens) |
| SSM access             | IAM scoped to `/revolver/*` (prod) or `/revolver-dev/*` (dev) parameters only |
| KMS decryption         | Restricted to SSM service context with parameter ARN condition             |
| Config caching         | SSM values cached for 5 min (no per-request SSM calls); required parameters missing → 503, no fallback defaults |
| Flooding               | Account concurrency limit (10), input checks before Volvo, throttle + traffic alarms (see Limits and Alarms) |
| Pairing tokens         | DynamoDB, encrypted at rest; max 10 min (checked in code, TTL cleans up); delivered once via conditional delete; only `sha256(secret)` stored; never returned to the browser |

## Cost

**Free** for personal use:

- Lambda: 1M free requests/month
- Function URL: no additional cost
- SSM Parameter Store: free for standard parameters
- DynamoDB (pairing): on-demand, a few hundred requests per login, fractions of a cent
- KMS: free for SSM default key (`aws/ssm`)
- CloudWatch alarms: 10 free per account, then $0.10 per alarm per month (3 per stack)
- SNS email: first 1000 emails/month free

## Rotate Secrets

Update SSM parameter — no redeploy needed:

```bash
aws ssm put-parameter \
  --name /revolver/client-secret \
  --value "new-secret" \
  --type SecureString \
  --overwrite
```

Warm instances pick up the new value within 5 minutes (config cache). To apply it at once, force a cold start:

```bash
aws lambda update-function-configuration \
  --function-name ReVolverAuthStack-token-exchange \
  --description "reload $(date +%s)"
```
