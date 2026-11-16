# Feature Plans

Planned features, one section each. Status: `planned` → `in progress` → `done`.

| # | Feature | Status | Source |
|---|---------|--------|--------|
| 1 | [Quick Launch action](#1-quick-launch-action) | planned | User request |
| 2 | [Volvo ID → Keycloak migration](#2-volvo-id--keycloak-migration) | in progress | Volvo announcement — **deadline 2027-01-31** |
| 3 | [Dev environment (dev credentials + endpoint)](#3-dev-environment) | in progress | Development need — **do before #2** |
| 4 | [Browser login with pairing](#4-browser-login-with-pairing) | in progress | Volvo login page blank in the Pebble settings webview — **blocks all logins** |

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

**Status:** in progress (`feature/volvo_id_migration`). Prod switch waits for the overnight refresh-token check (see "Open questions").
**Deadline:** 2027-01-31. After that date, OAuth clients with a `dc-` client ID stop working.

### Sources

- Volvo announcement (2026-10-26): https://developer.volvocars.com/news/volvoid-migration/ (requires a developer portal login)
- Community migration notes: [runsten#253](https://github.com/runsten-app/runsten/issues/253), [evcc#35845](https://github.com/evcc-io/evcc/pull/35845), [evcc#36007](https://github.com/evcc-io/evcc/issues/36007), [homey-com.volvocars#72](https://github.com/ricott/homey-com.volvocars/pull/72)

### What changes

| Item | Old | New |
|------|-----|-----|
| Issuer / discovery | `https://volvoid.eu.volvocars.com/.well-known/openid-configuration` | `https://auth.volvocars.com/realms/volvocars/.well-known/openid-configuration` |
| Authorize | `https://volvoid.eu.volvocars.com/as/authorization.oauth2` | `https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth` |
| Token | `https://volvoid.eu.volvocars.com/as/token.oauth2` | `https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/token` |
| Client ID | `dc-…` | `vid-dc-…` (**new application** in the developer portal) |
| Client secret, `vcc-api-key` | current | new |
| Scopes | current | same. **No `offline_access`**: Keycloak rejects it with `invalid_scope` for `vid-dc-` clients (tested on dev, 2026-11-12). |
| Redirect URI | — | Set when the app is created; **the portal can't edit it later**. Prod: `https://piotrserafin.github.io/ReVolverAuth/`. |
| Existing tokens | — | **Cannot be migrated.** Every user logs in again once. |

Verified against the [discovery document](https://auth.volvocars.com/realms/volvocars/.well-known/openid-configuration): endpoints above, all current scopes (incl. `energy:*`), PKCE S256 and `client_secret_basic` (the Lambda's Basic auth). Claim renames (`firstname` → `given_name`, `client_id` → `azp`) don't matter: ReVolver doesn't read the id_token.

### Current state (2026-11-16)

- **Dev** runs fully on Keycloak with its own `vid-dc-` app (`/revolver-dev/*`). Login (browser pairing, #4) and commands work.
- **Prod** (v1.2.0) still uses the old client and endpoints. Volvo forwards the old authorize URL to the Keycloak login page, and the old token endpoint still accepts the code. Works until 2027-01-31.
- **Auth page** already accepts both login origins (`ALLOWED_AUTH_ORIGINS` in `auth/index.html`).
- **Lambda** defaults (`DEFAULT_AUTH_ENDPOINT`, `DEFAULT_TOKEN_ENDPOINT`) point at Keycloak. Prod sets both in SSM, so the defaults only matter if a parameter is missing.
- **PebbleKit JS:** no change. Old refresh tokens fail with 400/401 after the switch; `refreshToken()` clears them, and the watch shows "Login needed".

### Steps

1. **Overnight check (blocking):** dev build logged in, untouched for 8+ h → still "Ready" in the morning? Without `offline_access` the refresh token may be tied to the SSO session. If it dies overnight, don't switch prod; ask Volvo developer support first.
2. **Volvo developer portal** (manual): create the prod application → `vid-dc-…` client ID, secret, API key. Redirect URI `https://piotrserafin.github.io/ReVolverAuth/` (exact, with trailing slash). Same scopes as `/revolver/scopes` today, incl. `energy:state:read` and `energy:capability:read`. Publish it if the portal requires that before cars respond.
3. **Save the current `/revolver/*` values** for rollback (run by the user; secrets stay out of chat).
4. **SSM switch** (run by the user): `put-parameter --overwrite` for `client-id`, `client-secret`, `vcc-api-key`, `auth-endpoint`, `token-endpoint` (and `scopes` if they change). Then force a Lambda cold start, because config is cached per container:
   `aws lambda update-function-configuration --function-name ReVolverAuthStack-token-exchange --description "ReVolver OAuth2 token exchange proxy for Volvo ID $(date +%s)"`
5. **Test with v1.2.0** (no new app release needed): log in via the browser → commands, status, Energy API (battery) → token refresh after > 1 h idle and overnight.
6. **Tell users** (store + GitHub release notes): "Log in once again."
7. **Rollback** (until 2027-01-31): restore the saved SSM values + cold start.
8. **Cleanup after 2027-01-31:** remove `volvoid.eu` from `ALLOWED_AUTH_ORIGINS` and the diagnostics page, delete the old application in the portal.

### Not available

- **Device Authorization flow (RFC 8628):** the realm advertises it, but it's disabled for `vid-dc-` clients (`unauthorized_client`: "The flow is disabled for the client", tested 2026-11-12). It would have removed the auth page; not possible unless Volvo enables it per client.
- **`offline_access`:** rejected (`invalid_scope`), see above.

### Open questions

- Does the refresh token survive overnight without `offline_access`? (step 1)
- Does the new prod application need Volvo approval/publishing before cars respond? (evcc notes car status only resumes after publishing)
- Optional: revoke old refresh tokens on re-login (`revocation_endpoint` via a Lambda `grant_type=revoke`).

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

## 4. Browser login with pairing

**Status:** in progress (`feature/browser-pairing`; works end-to-end on dev, 2026-11-16)

### Problem

Volvo's Keycloak login page renders blank in the Core Devices Pebble app's settings webview (Android), so nobody can log in. The old `volvoid.eu` login URL now forwards to the same page, so prod is affected too.

Root cause (confirmed 2026-11-14): the settings webview injects `realm_guard.js` (commit [f5f688fe16](https://github.com/coredevices/mobileapp/commit/f5f688fe16cf40befd5a3e13ad6016caf88548eb)), which deletes `window.customElements`. Volvo's login bundle calls `window.customElements.get('track-event')` at module load (analytics), throws, and React unmounts. It was reproduced in desktop Chrome by injecting the guard, and the diagnostics page shows `customElements` missing on the device. Reported upstream as [coredevices/mobileapp#507](https://github.com/coredevices/mobileapp/issues/507) with a suggested fix (an inert registry instead of deleting it). We can't change either side, so we log in outside the webview.

Related, also needed: `pebble.usesPermissions` in `package.json` (declared domains). Without it the webview blocks every host silently.

### Flow

```
Settings open → PKJS: POST action=pair_start → {code, secret}; secret stays in PKJS (localStorage)
             → Clay link = AUTH_URL?pair=<code>; PKJS polls every 3 s
Webview      → auth page sees ?pair + Pebble.openUrl → "Log in with Volvo ID in browser"
             → Pebble.openUrl(AUTH_URL?pair=<code>) → phone browser
Browser      → pair saved in sessionStorage → Volvo login (PKCE) → back with ?code
             → POST exchange + pair → Lambda stores tokens on the pairing, returns {ok:true}
             → "Connected. Go back to the Pebble app."
PKJS poll    → POST action=pair_poll(code, secret) → 202 pending … → 200 tokens (item deleted)
             → saveAuth → sendStatus → watch "Logged in!" + "Ready"
```

The in-webview login stays as a fallback ("Log in here instead"), so it works again once the Pebble app is fixed. If `pair_start` fails, the settings page opens without `?pair` (old flow).

### Changes

| Component | Change |
|-----------|--------|
| CDK | DynamoDB table `<stack>-pairing` (on-demand, TTL attribute `ttl`, `DESTROY`); Lambda gets Put/Get/Update/DeleteItem on it, plus env `PAIRING_TABLE`. **Prod template changes too** (new table), so merging deploys it. |
| Lambda | `action=pair_start` → random `code` (16 B) + `secret` (32 B); stores `sha256(secret)` and `ttl` = now + 10 min. Exchange with `pair` → tokens go onto the item (conditional: exists, not used, not expired) → `{ok:true}`; 410 if expired or used. `action=pair_poll` → 404 (unknown, wrong secret or expired all look the same), 202 pending, 200 tokens via a conditional delete (delivered once). |
| Auth page | `?pair` in the webview → "in browser" button (`Pebble.openUrl`) + fallback link. `?pair` in the browser → kept in sessionStorage through the Volvo round trip, sent with the exchange, then a "go back to Pebble" screen. Without `?pair`: unchanged. |
| PKJS | Clay rebuilt on every settings open (fresh code in the link). `pair_start` → `openURL` → poll every 3 s until 200/404/expiry. Polling resumes on `ready`. `saveAuth()` is shared with the webview payload path. |

### Security

- Tokens never reach the browser. They wait at most 10 min in DynamoDB (encrypted at rest), are handed out once, then deleted.
- The `code` travels through the browser (URL, history); the `secret` never leaves PKJS and is stored only as a hash.
- Known gap: someone who learns a live `code` could attach *their* Volvo account to the pairing (login CSRF). Low risk (128-bit code, 10 min). Fix later if needed: show a short confirmation code on the watch and the browser.
- No rate limit on `pair_start`; TTL cleans up. DynamoDB TTL deletes lazily, so expiry is also checked in code.

### Risks / open questions

- `Pebble.openURL` is now called after an async request (`pair_start`, ~6 s on a Lambda cold start). Check that the Pebble app still opens settings, and that the delay is acceptable.
- Does PKJS keep running (polling) while the browser is in front? If not, polling resumes on `ready` within the 10-min window.
- Does Akamai accept the login in the phone browser? Yes: Chrome already worked before this feature.
- Polling while settings are open only to change the VIN: up to 200 small requests per open. Fine for a PoC; add backoff if it matters.

### Testing

- [x] Lambda pairing logic: local test with a fake DynamoDB (18 checks: pending, wrong secret, single delivery, expiry, 410, plain exchange unchanged, origin check).
- [x] PKJS: node simulation (pair link, polling, token save, `+Logged in!`, 404 stop, fallback, resume on `ready`).
- [x] Auth page: headless Chrome with mocked Lambda and `Pebble` (webview button, `openUrl`, sessionStorage round trip, done screen, 410, no-pair unchanged).
- [x] `cdk synth -c stage=dev`: table, grant, env var.
- [x] `cdk deploy -c stage=dev`.
- [x] Push the branch → dev auth page.
- [x] Phone, dev build: settings → browser → Volvo login → watch "Logged in!" (Pixel 8, Android 17 DP11).
- [x] Prod merge (PR #3). The merge push event was lost during a GitHub incident; deployed with manual `workflow_dispatch` runs.
- [x] Phone, prod build: browser login works.
- [ ] Release `v1.2.0` (with `usesPermissions`).
