# Feature Plans

Planned features, one section each. Status: `planned` → `in progress` → `done`.

| # | Feature | Status | Source |
|---|---------|--------|--------|
| 1 | [Quick Launch action](#1-quick-launch-action) | planned | User request |
| 2 | [Volvo ID → Keycloak migration](#2-volvo-id--keycloak-migration) | planned | Volvo announcement — **deadline 2027-01-31** |
| 3 | [Dev environment (dev credentials + endpoint)](#3-dev-environment) | in progress | Development need — **do before #2** |

---

## 1. Quick Launch action

**Status:** planned

### Request

> The option to set a Quick Launch directly to the action "Climate on" (or a range of different actions). This would allow me to activate the climate with a simple push of one of the Pebble's buttons.

### Platform constraint

Pebble Quick Launch only **launches the app**. It passes no arguments, and every Quick Launch button launches the app the same way. The app can only detect `launch_reason() == APP_LAUNCH_QUICK_LAUNCH`, not which button was pressed.

→ **One Quick Launch action per app**, chosen in settings. Mapping different buttons to different actions is not possible.

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Confirm step on Quick Launch | Skipped | Quick Launch is an explicit intent; BACK cancels before the send |
| Unlock available as quick action | No | Safety: a stray button press must not open the car |
| Auto-exit after result | Optional, off by default | User choice via a Clay toggle |

### Settings (`src/pkjs/config.json`)

New "Quick Launch" section:

- `select` with message key `QUICK_ACTION`:

  | Label | Value |
  |-------|-------|
  | None (default) | `""` |
  | Climate On | `climatization-start` |
  | Climate Off | `climatization-stop` |
  | Lock | `lock` |
  | Flash Lights | `flash` |
  | Honk + Flash | `honk-flash` |
  | Engine Start 5 min | `engine-start:5` |
  | Engine Start 10 min | `engine-start:10` |
  | Engine Start 15 min | `engine-start:15` |
  | Engine Stop | `engine-stop` |

- `toggle` with message key `QUICK_EXIT`: "Close app after Quick Launch action" (default off).

Values reuse the existing `COMMAND` string format, so the JS command path stays the same.

### Message keys (`package.json`)

| Key | Direction | Type | Purpose |
|-----|-----------|------|---------|
| `QUICK_ACTION` | JS → Watch | string | Command to run on Quick Launch (`""` = none). Persisted on watch. |
| `QUICK_EXIT` | JS → Watch | int | 1 = exit app after the quick action result. Persisted on watch. |

### JS (`src/pkjs/index.js`)

- In `webviewclosed` (Clay branch), read `QUICK_ACTION` and `QUICK_EXIT`, unwrapping `.value` and falling back to numeric keys the way `VIBRATE` does, and `send()` both to the watch.
- No other changes: the quick action reaches JS as a normal `COMMAND`, and `executeCommand` already handles token refresh, the 401 retry, the availability check and the result text.

### Watch (C)

**`modules/messaging.c`**
- On receiving `QUICK_ACTION` / `QUICK_EXIT`, persist them (`persist_write_string` / `persist_write_bool`), like `VIBRATE`.
- Track the "JS ready" state: the first inbox message of the session means PebbleKit JS is running. JS always sends `STATUS_MSG` on `ready` (`Refreshing...` if the token expired, otherwise `sendStatus()`).
- Expose `messaging_send_command(const char *cmd)`. Move the outbox code out of `commands.c` `on_action` **and** `main_window.c` `on_up` (the `refresh` send) so all paths share it.
- **Suppress `STATUS_MSG` while a quick action is busy** (`quick_launch_is_busy()`: armed, sent, or result still shown). Otherwise the launch flow overwrites the quick-action status: `sendStatus()` sends `Ready`, then `fetchCommandAccessibility()` sends `Ready`/`Driving` while the command is in flight. A late `STATUS_MSG` also cancels `s_revert_timer` in `main_window_set_status()`, so the result text ("Climate on!") would vanish before its 3 s.

**New `modules/quick_launch.h/.c`**
- `quick_launch_init()`: if `launch_reason() == APP_LAUNCH_QUICK_LAUNCH` and a persisted `QUICK_ACTION` is non-empty, arm a pending action and set the status to the action label (e.g. "Climate On...").
- `quick_launch_on_js_ready()`: called by messaging on the first inbox message; sends the pending command once, then disarms.
- Timeout (~10 s via `app_timer`): if JS has not become ready, show "Phone not ready" with the error vibration and disarm.
- BACK before the send: cancel the pending action (the window's normal BACK closes the app, which is enough).
- `quick_launch_on_result()`: called from the `COMMAND_RESULT` handler; if `QUICK_EXIT` is on and this was the quick action, `app_timer` ~3 s → `window_stack_pop_all(true)`.

**`main.c`**
- Call `quick_launch_init()` after `messaging_init()` and `main_window_push()`.

**Label lookup**
- Map the command string to its display label using the existing `COMMANDS[]` table in `commands.c` (expose a `commands_label_for(const char *cmd, char *buf, size_t len)` helper) instead of duplicating labels.
- Match on the part before `:`: the table `path` is `engine-start`, the quick action is `engine-start:5`. Append the parameter to the label (e.g. "Engine Start 5 min").

### Edge cases

| Case | Behavior |
|------|----------|
| Quick action not supported by car (bitmask) | JS returns `-Not supported`, error vibration |
| Token expired on launch | JS `ready` refresh and `executeCommand` refresh go through the existing refresh lock |
| Phone disconnected | Timeout → "Phone not ready" |
| Normal launch (from menu) | No quick action; app behaves as today |
| `QUICK_ACTION` = None | Quick Launch opens the app normally |
| Persisted action is `unlock` (e.g. old data) | Rejected on the watch side; never sent |
| Launch `STATUS_MSG` (`Ready`, `Driving`, `Refreshing...`) arrives during the quick action | Ignored while `quick_launch_is_busy()`; normal status handling resumes after the result |

### Docs to update

- `AGENTS.md`: message key table, project structure (`quick_launch.c`), new "Quick Launch" section.
- `doc/sequences.md`: Quick Launch sequence diagram. **The file doesn't exist yet** (`AGENTS.md` refers to it); create it with the existing flows (first launch, subsequent launch, command + 401 retry) plus Quick Launch.

### Testing

- `pebble build` for all platforms.
- Emulator: the SDK has no direct Quick Launch trigger. Temporarily force the launch-reason check to true (debug `#define`) to exercise the flow, and verify with screenshots: status "Climate On..." → "Climate on!" → (exit if enabled).
- Real watch: Settings → Quick Launch → assign ReVolver to a button and confirm the end-to-end flow.

---

## 2. Volvo ID → Keycloak migration

**Status:** planned
**Deadline:** 2027-01-31. After that date, OAuth clients with a `dc-` client ID stop working.

### Sources

- Volvo announcement (2026-10-26): https://developer.volvocars.com/news/volvoid-migration/ (requires a developer portal login; not read directly, so verify against it)
- Community migration notes: [runsten#253](https://github.com/runsten-app/runsten/issues/253), [evcc#35845](https://github.com/evcc-io/evcc/pull/35845), [evcc#36007](https://github.com/evcc-io/evcc/issues/36007), [homey-com.volvocars#72](https://github.com/ricott/homey-com.volvocars/pull/72)

### What changes

| Item | Old | New |
|------|-----|-----|
| Issuer / discovery | `https://volvoid.eu.volvocars.com/.well-known/openid-configuration` | `https://auth.volvocars.com/realms/volvocars/.well-known/openid-configuration` |
| Authorize | `https://volvoid.eu.volvocars.com/as/authorization.oauth2` | `https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth` |
| Token | `https://volvoid.eu.volvocars.com/as/token.oauth2` | `https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/token` |
| Client ID | `dc-…` | `vid-dc-…` (**new application** in the developer portal) |
| Client secret | current | new |
| `vcc-api-key` | current | new (one report says the old key keeps working with the new client; don't rely on it) |
| Scopes | current `conve:*`, `openid`, `location:read` | same, plus **`offline_access`** |
| Existing tokens | — | **Cannot be migrated.** Every user logs in again once. |

**Verified against the [discovery document](https://auth.volvocars.com/realms/volvocars/.well-known/openid-configuration) (2026-11-11):**
- The authorize/token endpoints above are correct.
- All 28 current scopes (`doc/scopes.md`, incl. `energy:state:read` and `energy:capability:read`) plus `offline_access` are in `scopes_supported` (re-checked 2026-11-12).
- PKCE S256 and `client_secret_basic` (the Lambda's Basic auth) are supported.
- Also available: `revocation_endpoint` (`…/protocol/openid-connect/revoke`), `device_authorization_endpoint`, CIBA (`…/ext/ciba/auth`), PAR (optional, `require_pushed_authorization_requests: false`).
- `energy:*` scopes exist (`energy:battery_charge_level`, `energy:recharge_status`, `energy:electric_range`, `energy:charging_connection_status`, `energy:estimated_charging_time`, …).
**Not affected:** claim renames (`firstname` → `given_name`, `client_id` → `azp`). ReVolver doesn't read the id_token.

### Why `offline_access` matters

Without it, Keycloak ties the refresh token to the SSO session, which lasts hours to days, so users would be logged out regularly. With it, the refresh token outlives the browser session. This may also fix the known issue "occasional re-login needed after ~1h idle"; verify after the migration.

### Impact on ReVolver

| Component | Change needed |
|-----------|---------------|
| **ReVolverAuth** (`auth/index.html` in this repo) | `ALLOWED_AUTH_ORIGIN = 'https://volvoid.eu.volvocars.com/'` is hardcoded (line 22, checked at line 119). **It blocks login** against the new endpoint. It must allow `https://auth.volvocars.com/` **before** the backend switches. Deployed by `.github/workflows/deploy-auth.yml` on push to `main` (`auth/**`), which syncs to the ReVolverAuth repo / GitHub Pages. |
| **Lambda** (`token_exchange.py`) | Endpoints already come from SSM (`auth-endpoint`, `token-endpoint`), so the switch can be config-only. Update `DEFAULT_AUTH_ENDPOINT` / `DEFAULT_TOKEN_ENDPOINT` so the code doesn't fall back to dead URLs. Deployed by `.github/workflows/deploy-lambda.yml` (`cdk deploy --require-approval never`) on push to `main` (`infra/**`): **merging is the deploy**. |
| **SSM** | New values: `client-id`, `client-secret`, `vcc-api-key`, `auth-endpoint`, `token-endpoint`, `scopes` (+ `offline_access`). `scopes` is effectively required: `auth/index.html` rejects a config without it. |
| **PebbleKit JS** | No URL changes (it talks only to the Lambda). Old refresh tokens fail with 400 `invalid_grant` (or 401 `invalid_client`); `refreshToken()` **already clears the stored tokens on 400/401**, so the next launch shows "Login needed". |
| **Watch (C)** | None. |
| **Docs** | `doc/scopes.md` (+ `offline_access`), `AGENTS.md` (SSM defaults, known issues), `infra/lambda/README.md`. Note: `AGENTS.md` refers to `doc/auth.md`, `doc/plan.md` and `doc/sequences.md`, which don't exist in the repo; restore them or remove the references. |

### Cutover strategy

**Option A: hard cutover (recommended).** The user base is small and every user has to re-login anyway. Pick a date, switch SSM, and post a note asking users to log in again.

**Stretch, after A:** device flow login. It removes the ReVolverAuth frontend; see [Stretch: Device Authorization flow](#stretch-device-authorization-flow-rfc-8628).

**Option B: dual-client Lambda until the deadline.** Keep the legacy config under `/revolver/legacy/*`. On refresh, try the new client, and on `invalid_grant`/`invalid_client` fall back to legacy. This avoids a forced re-login only until 2027-01-31, so it's more code for little gain. Not recommended.

### Steps (Option A)

1. **Volvo developer portal** (manual): create a new application → `vid-dc-…` client ID, secret and API key. Same redirect URI (`https://piotrserafin.github.io/ReVolverAuth/`), same scopes plus `offline_access`. **Include `energy:state:read` and `energy:capability:read`**: the Energy API is already in use (EV battery status, commit 475664f). Missing scopes mean another user re-login later. Publish the app if the portal requires that before cars respond.
2. **ReVolverAuth:** in `auth/index.html`, change `ALLOWED_AUTH_ORIGIN` to accept both `https://volvoid.eu.volvocars.com/` and `https://auth.volvocars.com/`. Merge to `main` → `deploy-auth.yml` publishes it. This is harmless before the switch.
3. **Lambda code:** update the default endpoints to Keycloak. Optionally map `invalid_grant` on refresh to a distinct error (`reauth_required`). Check with `cdk synth`; merging to `main` runs `cdk deploy` via `deploy-lambda.yml`, so **the merge needs confirmation**.
4. **SSM switch** (needs confirmation): `put-parameter --overwrite` for `client-id`, `client-secret`, `vcc-api-key`, `auth-endpoint`, `token-endpoint`, `scopes`. The Lambda caches config per container, so force a cold start (redeploy or update an env var) so the new values take effect immediately.
5. **PebbleKit JS** (optional): token clearing is **already done**: `refreshToken()` clears the tokens on 400/401, and the next `sendStatus()` shows "Login needed". Remaining options: map `reauth_required` (if added in step 3) the same way, and show "Login needed" instead of "Re-login needed" right away on a failed manual refresh.
   - Optional: a Lambda `grant_type=revoke` → `revocation_endpoint`, called by JS before a re-login or a VIN change, so old refresh tokens don't stay valid.
6. **Re-login** on the phone via Clay → "Log in with Volvo ID" → check that commands work.
7. **Verify on a real car:**
   - Access token lifetime (`expires_in`): is the 60 s refresh threshold still fine?
   - Refresh token rotation is still single-use, so the refresh lock stays.
   - The refresh token survives > 1 h idle and overnight (`offline_access`).
   - The `invalid_grant` response shape for a dead refresh token.
   - The Energy API (`/capabilities`, `/state`) still returns battery data with the new client.
8. **Rollback:** keep the old SSM values in a note until verified. While the old client is still alive (before 2027-01-31), restoring the SSM values plus the Lambda cold start rolls back. ReVolverAuth accepts both origins, so it needs no rollback.
9. **Cleanup after 2027-01-31:** remove the `volvoid.eu` origin from ReVolverAuth and delete the old application in the portal.

### Stretch: Device Authorization flow (RFC 8628)

**Goal:** remove the ReVolverAuth GitHub Pages frontend, the redirect URI and the CORS origin handling. The Lambda stays, because it still holds `client_secret` and `vcc-api-key`.

**Precondition (blocking):** Volvo must enable the device grant for the `vid-dc-…` client. The realm advertises `device_authorization_endpoint` and the `urn:ietf:params:oauth:grant-type:device_code` grant, but Keycloak enables it **per client**. Check the portal app settings or ask Volvo developer support. If it's not available, skip this section; the migration above is complete without it.

**Do this after** the base migration is verified. It's a separate release.

#### Flow

```
Watch: "Login needed" → SELECT → "Log in"
  JS  → Lambda  POST grant_type=device_start
  Lambda → Volvo POST /protocol/openid-connect/auth/device   (Basic auth, scope incl. offline_access)
        ← device_code, user_code, verification_uri(_complete), expires_in, interval
  JS  → Watch   LOGIN_CODE="ABCD-EFGH", LOGIN_URL="auth.volvocars.com/…/device"
  JS  → Pebble.openURL(verification_uri_complete)   (optional: login in the phone webview, code prefilled)
  JS  polls Lambda every `interval` s: POST grant_type=urn:ietf:params:oauth:grant-type:device_code&device_code=…
        authorization_pending → keep polling
        slow_down             → interval += 5 s
        expired_token         → "Code expired", offer retry
        access_denied         → "Login cancelled"
        200                   → store tokens (same shape as today, incl. vcc_api_key) → sendStatus()
```

#### Changes

| Component | Change |
|-----------|--------|
| **Lambda** | New `grant_type=device_start` → call the device authorization endpoint with client auth and scopes from SSM. Accept `urn:ietf:params:oauth:grant-type:device_code` in `_handle` and forward it to the token endpoint. Response shape unchanged (`vcc_api_key` included). New SSM param `/revolver/device-endpoint` (optional, Keycloak default in code). |
| **PebbleKit JS** | `startDeviceLogin()`: request a code, send it to the watch, poll with backoff, and handle the RFC 8628 errors. Optionally open `verification_uri_complete` via `Pebble.openURL` (webview); on `webviewclosed`, keep polling. Polling runs only while the app is open (known `setTimeout` caveat). |
| **Watch (C)** | New message keys `LOGIN_CODE` (string) and `LOGIN_URL` (string). Show a login screen with the large code, the short URL and the expiry countdown. Add a `LOGIN` value for the `COMMAND` key to start the flow from the watch. |
| **Clay** | Replace the "Log in with Volvo ID" link with a button/toggle that starts the device login, or with text: "Open ReVolver on the watch → Log in". |
| **Removed (after transition)** | ReVolverAuth repo/site, `handle_config` GET, the `authorization_code` handler, SSM `redirect-uri` and `allowed-origins`, the auth-response branch in `webviewclosed`, CORS logic. |

#### Security notes

- A `device_code` can be redeemed through the public Lambda by anyone who holds it, the same exposure as today's auth code. Mitigations: it's short-lived (`expires_in`), it's only ever sent over HTTPS to PebbleKit JS, and it's never logged in the Lambda.
- `user_code` phishing is a known risk for device flow. Show the exact verification URL on the watch, and never accept codes from third parties.
- Optional: add a rate limit on `device_start` (Lambda reserved concurrency or a simple per-IP limit) so the endpoint can't be used to spam Volvo.

#### Testing

- Emulator: the full flow with a real Volvo account (the code is shown on the watch, approved in the browser).
- Error paths: let the code expire, deny the consent, and close the app mid-poll → the next launch shows "Login needed".
- Check that the refresh token issued by device flow behaves the same as the one from the auth code flow (`offline_access`, rotation).

### Open questions

- Is the device grant enabled for `vid-dc-…` clients (stretch above)?
- Is CIBA (`backchannel_authentication_endpoint`, approval pushed to the Volvo Cars app) available to third-party clients? It would be an even simpler watch login than device flow (no code to type), but it's unlikely to be available. Ask in the same support request.
- Does the new application need Volvo approval/publishing before production use (evcc notes car status only resumes after publishing)?
- Is the redirect URI accepted unchanged by Keycloak (exact match, trailing slash)?
- Does the old `vcc-api-key` keep working (one community report says yes)? Use the new one regardless.

---

## 3. Dev environment

**Status:** in progress

**Progress (2026-11-12):**
- [x] Infra: `stage` context, `ReVolverAuthStack-dev`, `/revolver-dev` prefix. Prod synth byte-identical to before.
- [x] Dev stack deployed: `https://ckcflhkgzt3p6lsxad5uvxom740fkwbr.lambda-url.eu-central-1.on.aws/`
- [x] `wscript` → `env.js` + `-DREVOLVER_DEV`; `index.js` uses `env.LAMBDA_URL`, Clay link `{{AUTH_URL}}`; "DEV" tag on watch.
- [x] ~~`auth/index.html`: `?env=dev` switching~~ — merged (#1), then **reverted** (#2) while prod webview login was broken. Cause turned out to be Volvo: the old login URL now forwards to the Keycloak login page, which renders blank in the Pebble Android webview (see #4).
- [x] Replaced by **separate deployments**: prod page from the `ReVolverAuth` repo (`deploy-auth.yml`, `main`), dev page from a separate `ReVolverAuth-dev` repo (`deploy-auth-dev.yml`, any other branch, dev Lambda URL substituted at deploy). `auth/index.html` accepts both login origins (`volvoid.eu`, `auth.volvocars.com`).
- [ ] Create the `ReVolverAuth-dev` repo with GitHub Pages, and add the deploy key (secret `REVOLVERAUTH_DEV_DEPLOY_KEY`).
- [ ] Dev Volvo app: add redirect URI `https://piotrserafin.github.io/ReVolverAuth-dev/`; set `/revolver-dev/redirect-uri` to it.
- [ ] Dev Volvo app + `/revolver-dev/*` SSM params (extended scopes).
- [ ] Merge to `main` → auth page live (dev login needs it); infra deploy is a no-op for prod.
- [ ] End-to-end: dev build → login → commands.
- [x] `doc/scopes.md`: dev-only scopes (`location:read`; prod SSM checked 2026-11-12: 27 scopes, no `location:read`).

### Goal

Develop and test against **dev credentials** (a separate Volvo application: client ID, secret, `vcc-api-key`) through a **separate dev Lambda endpoint**, without touching production users.

**Do this before #2.** The Keycloak migration can then be built and verified on dev (new `vid-dc-…` app, `offline_access`, refresh behavior) while prod keeps running unchanged.

### Design

```
              dev build (REVOLVER_ENV=dev)          prod build (default)
PebbleKit JS  LAMBDA_URL = dev Function URL         LAMBDA_URL = prod Function URL
Auth page     ReVolverAuth-dev/                     ReVolverAuth/
Lambda        ReVolverAuthStack-dev                 ReVolverAuthStack (unchanged)
SSM           /revolver-dev/*                       /revolver/* (unchanged)
Volvo app     "ReVolver Dev" (unpublished)          "ReVolver" (published)
```

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SSM prefix for dev | `/revolver-dev` | Not `/revolver/dev`: prod's IAM policy grants `parameter/revolver/*`, so prod would be able to read dev secrets. A separate prefix also needs no prod migration. |
| Stage selection (infra) | CDK context: `cdk deploy -c stage=dev` | One stack class, two stacks; the prod stack name and Function URL stay the same. |
| Stage selection (watch app) | **Build time**: `REVOLVER_ENV=dev pebble build` | The dev URL never ships in a release `.pbw`, and nobody can switch to dev by accident. A runtime Clay toggle was rejected for that reason. |
| Auth frontend | Separate repo `ReVolverAuth-dev` (own GitHub Pages site and deploy key), deployed by its own workflow from any branch | Prod page only changes on `main`. (The first approach, `?env=dev` switching in one page, was reverted: an experiment on the shared page put prod at risk.) |
| Volvo app for dev | Separate, **unpublished** application | Unpublished apps work for the owner's own account: ideal for dev. Own client ID, secret, API key and redirect URI. |

### Changes

**Infra (`infra/app.py`, `infra/lib/revolver_auth_stack.py`)**
- `app.py`: read `stage = app.node.try_get_context("stage") or "prod"`. Prod → `ReVolverAuthStack` (same name as today), dev → `ReVolverAuthStack-dev`.
- Stack: take `stage` as a parameter. `ssm_prefix = "/revolver" if prod else "/revolver-dev"`. Pass `SSM_PREFIX` to the Lambda env (the Lambda already reads it). Scope the IAM role and the KMS condition to that prefix. Make the role name unique per stack (already `{stack_name}-lambda-role`).
- Output the Function URL per stack (the `CfnOutput` already exists).
- **CI deploys prod only.** `deploy-lambda.yml` runs `cdk deploy` (no context → prod) on every push to `main` touching `infra/**`. Merging this refactor deploys prod immediately, so confirm the prod template is unchanged **before** merging (see Testing). The dev stack is always deployed manually.

**Lambda (`token_exchange.py`)**
- No code change: `SSM_PREFIX` is already supported.

**SSM (manual, dev only)**
- `/revolver-dev/client-id`, `client-secret`, `vcc-api-key` (SecureString) from the dev Volvo app.
- `/revolver-dev/redirect-uri` (the dev app's registered redirect URI), `allowed-origins` (`https://piotrserafin.github.io,https://piotrserafin.dev`; Pages redirects to the `.dev` custom domain), `scopes` (**required**: the auth page rejects a config without it). Dev uses an **extended scope list**: prod scopes + `location:read` (see `doc/scopes.md`); every scope must also be enabled on the dev Volvo app, or authorize fails with `invalid_scope`. `offline_access` only with Keycloak endpoints. Plus `auth-endpoint`/`token-endpoint` if they differ from the defaults (e.g. Keycloak while prod is still legacy).

**Auth frontend (`auth/index.html`, deployed to the ReVolverAuth repo)**
- One source (`auth/`), two deployments. `deploy-auth-dev.yml` copies it to the `ReVolverAuth-dev` repo and rewrites `var LAMBDA_URL` to the dev Lambda (the page fetches its OAuth config from it, so this also picks the dev Volvo app). It adds `[DEV]` markers and `noindex`, and writes `version.txt`.
- `deploy-auth.yml` (prod) is unchanged; the two sites share nothing but the source.

**PebbleKit JS (`src/pkjs/`)**
- `wscript`: before the build, generate `src/pkjs/env.js` from `os.environ.get('REVOLVER_ENV', 'prod')`:
  ```js
  module.exports = { ENV: 'dev', LAMBDA_URL: '…', AUTH_URL: 'https://piotrserafin.github.io/ReVolverAuth-dev/' };
  ```
- `index.js`: `var env = require('./env');` replaces the hardcoded `LAMBDA_URL`. `config.json` login link → `env.AUTH_URL`: Clay config is static JSON, so either patch the link in JS before `clay.generateUrl()`, or generate the link item in code.
- `.gitignore`: `src/pkjs/env.js`. A default prod `env.js` is generated if the variable is unset, so a plain `pebble build` = prod.

**Watch (optional)**
- Dev build: JS sends `STATUS_MSG` with a `[DEV] ` prefix, or the title shows "ReVolver DEV". Prevents confusing a dev install with prod on the wrist. No C change if done via the status prefix.

**Docs**
- `AGENTS.md`: Commands (`REVOLVER_ENV=dev pebble build`, `cdk deploy -c stage=dev`), the SSM table for `/revolver-dev`, Key URLs (dev Lambda).
- `infra/lambda/README.md`: the dev stack setup.

### Workflow

```bash
# one-time
cdk deploy -c stage=dev                     # → dev Function URL (put into env.js template + auth allowlist)
aws ssm put-parameter --name /revolver-dev/client-id ... --type SecureString   # etc.

# daily dev
REVOLVER_ENV=dev pebble build && pebble install --emulator basalt --vnc
# log in via Clay → ReVolverAuth-dev/ → dev Volvo app → dev Lambda

# release
pebble clean && pebble build                # prod (default)
```

### Edge cases

| Case | Behavior |
|------|----------|
| Dev and prod tokens mixed | Can't happen: sideloading clears PebbleKit JS localStorage, so switching builds forces a re-login. |
| Forgot `REVOLVER_ENV` on a release | Default is prod. Risk only in the other direction: release built with `dev`. Mitigation: the `[DEV]` marker on the watch, plus a release checklist item. |
| Stale `env.js` after switching env | `wscript` always regenerates it; or `pebble clean` before switching. |
| `?env=foo` on the auth page | Treated as prod. |
| Dev Lambda abuse | Same exposure as prod (public Function URL, origin check). Optional: delete the dev stack when not in use (`cdk destroy -c stage=dev`); the SSM params are kept. |

### Testing

- `cdk synth -c stage=dev` and `cdk synth`: the prod template is **unchanged** (diff it against the current synth), and the dev template uses `/revolver-dev`. Do this before merging: the merge deploys prod via CI.
- Dev build → login → commands work with the dev Volvo app.
- Prod build → `env.js` has the prod URL, and a grep of the `.pbw` shows no dev URL.

---

## 4. _Next feature_

**Status:** planned

_TBD_
