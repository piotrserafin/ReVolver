# Feature Plans

Planned features, one section each. Status: `planned` → `in progress` → `done`.

| # | Feature | Status | Source |
|---|---------|--------|--------|
| 1 | [Quick Launch action](#1-quick-launch-action) | done (unreleased, v1.3.0) | User request |
| 2 | [Volvo ID → Keycloak migration](#2-volvo-id--keycloak-migration) | done (2026-11-17) | Volvo announcement — **deadline 2027-01-31**; old-app cleanup after the deadline |
| 3 | [Dev environment (dev credentials + endpoint)](#3-dev-environment) | done | Development need |
| 4 | [Browser login with pairing](#4-browser-login-with-pairing) | done (v1.2.0) | Volvo login page blank in the Pebble settings webview ([mobileapp#507](https://github.com/coredevices/mobileapp/issues/507)) |

---

## 1. Quick Launch action

**Status:** done (PR #7), tested on a watch (dev build). Ships in v1.3.0.

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

**Status:** done (2026-11-17). Prod runs on Keycloak with a new `vid-dc-` application; v1.2.0 from the store logs in without an app update. Remaining: the prod overnight check and the cleanup after 2027-01-31 (step 8).
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

### Current state (2026-11-17)

- **Dev** and **prod** both run on Keycloak, each with its own `vid-dc-` app (`/revolver-dev/*`, `/revolver/*`). Both apps have the same 28 scopes, incl. `location:read` (for #5).
- The old prod app (`dc-…`) stays in the portal as the rollback until 2027-01-31.
- **Auth page** already accepts both login origins (`ALLOWED_AUTH_ORIGINS` in `auth/index.html`).
- **Lambda** defaults (`DEFAULT_AUTH_ENDPOINT`, `DEFAULT_TOKEN_ENDPOINT`) point at Keycloak. Prod sets both in SSM, so the defaults only matter if a parameter is missing.
- **PebbleKit JS:** no change. Old refresh tokens fail with 400/401 after the switch; `refreshToken()` clears them, and the watch shows "Login needed".

### Steps

1. ✅ **Overnight check** on dev (2026-11-17): still "Ready" in the morning without `offline_access`.
2. ✅ **Volvo developer portal:** prod application created (`vid-dc-…`, redirect URI `https://piotrserafin.github.io/ReVolverAuth/`, 28 scopes).
3. ✅ **Saved the old `/revolver/*` values** for rollback (kept by the user, outside the repo).
4. ✅ **SSM switch:** `client-id`, `client-secret`, `vcc-api-key`, `auth-endpoint`, `token-endpoint`, `scopes` (copied from dev). Lambda cold-started:
   `aws lambda update-function-configuration --function-name ReVolverAuthStack-token-exchange --description "ReVolver OAuth2 token exchange proxy for Volvo ID $(date +%s)"`
5. ✅ **Tested with v1.2.0** from the store: browser login works. Pending: prod overnight check.
6. ✅ **Told users:** re-login notice in the store description.
7. **Rollback** (until 2027-01-31): restore the saved SSM values + cold start.
8. **Cleanup after 2027-01-31:** remove `volvoid.eu` from `ALLOWED_AUTH_ORIGINS` and the diagnostics page, delete the old application in the portal, delete the saved SSM values.

### Not available

- **Device Authorization flow (RFC 8628):** the realm advertises it, but it's disabled for `vid-dc-` clients (`unauthorized_client`: "The flow is disabled for the client", tested 2026-11-12). It would have removed the auth page; not possible unless Volvo enables it per client.
- **`offline_access`:** rejected (`invalid_scope`), see above.

### Open questions

- How long does a Keycloak refresh token live when unused? (`refresh_expires_in` in the token response; the old Volvo ID value was 7 days)
- Optional: revoke old refresh tokens on re-login (`revocation_endpoint` via a Lambda `grant_type=revoke`).

---

## 3. Dev environment

**Status:** done (2026-11-16). Dev runs end-to-end on Keycloak with its own Volvo application.

### Goal

Develop and test against **dev credentials** (a separate Volvo application) through a **separate dev Lambda and auth page**, without touching production users.

### Design

```
              dev build (REVOLVER_ENV=dev)          prod build (default)
PebbleKit JS  LAMBDA_URL = dev Function URL         LAMBDA_URL = prod Function URL
Auth page     ReVolverAuth-dev/                     ReVolverAuth/
Lambda        ReVolverAuthStack-dev                 ReVolverAuthStack
SSM           /revolver-dev/*                       /revolver/*
Volvo app     "ReVolver Dev" (vid-dc-, Keycloak)    "ReVolver" (vid-dc-, Keycloak, since #2)
```

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SSM prefix for dev | `/revolver-dev` | Not `/revolver/dev`: prod's IAM policy grants `parameter/revolver/*`, so prod could read dev secrets. |
| Stage selection (infra) | CDK context: `cdk deploy -c stage=dev` | One stack class, two stacks; the prod stack name and Function URL stay the same. |
| Stage selection (watch app) | **Build time**: `REVOLVER_ENV=dev pebble build` | The dev URL never ships in a release `.pbw`, and nobody can switch to dev by accident. |
| Auth frontend | Separate repo `ReVolverAuth-dev`, deployed by `deploy-auth-dev.yml` from any non-`main` branch | The prod page only changes on `main`. (A first approach, `?env=dev` switching in one page, was reverted in #2 because it put prod at risk.) |
| Volvo app for dev | Separate, **unpublished** application | Unpublished apps work for the owner's account. Own client ID, secret, API key and redirect URI. |

### What was built

- **Infra:** `infra/app.py` reads the `stage` context; the stack takes `stage` and uses SSM prefix `/revolver-dev` for dev. Prod synth stayed byte-identical. CI deploys prod only; the dev stack is deployed manually.
- **Watch app:** `wscript` generates `src/pkjs/env.js` (gitignored: `ENV`, `LAMBDA_URL`, `AUTH_URL`) and adds `-DREVOLVER_DEV`; dev builds show a "DEV" tag on the watch. `config.json` has an `{{AUTH_URL}}` placeholder filled by `index.js`.
- **Auth page:** one source (`auth/`), two deployments. `deploy-auth-dev.yml` rewrites `LAMBDA_URL` to the dev Lambda, adds `[DEV]` markers and `noindex`, and writes `version.txt` (branch@sha). It also hosts `diag.html` (webview diagnostics).
- **SSM (dev):** Keycloak endpoints, the `vid-dc-` client, redirect URI `https://piotrserafin.github.io/ReVolverAuth-dev/`, allowed origins `https://piotrserafin.dev,https://piotrserafin.github.io`, and the extended scope list (prod scopes + `location:read`, see `doc/scopes.md`). **No `offline_access`**: Keycloak rejects it for `vid-dc-` clients.

Learned along the way:
- The Volvo portal can't edit a redirect URI after the app is created; the dev app had to be recreated.
- Every scope in SSM must also be enabled on the Volvo app, or authorize fails with `invalid_scope`.

### Workflow

```bash
REVOLVER_ENV=dev pebble build               # dev build (DEV tag on the watch)
cdk deploy -c stage=dev                     # dev stack (manual)
git push <branch>                           # auth/** changes → dev auth page
pebble build                                # prod (default; CI release builds this)
```

Setup details: `infra/lambda/README.md` → "Dev Stack".

### Edge cases

| Case | Behavior |
|------|----------|
| Dev and prod tokens mixed | Can't happen: sideloading clears PebbleKit JS localStorage, so switching builds forces a re-login. |
| Release built with `REVOLVER_ENV=dev` | Default is prod. The "DEV" tag on the watch shows a wrong build; CI release builds never set the variable. |
| Stale `env.js` after switching env | `wscript` regenerates it on every build. |
| Dev Lambda abuse | Same exposure as prod (public Function URL, origin check). Optional: `cdk destroy -c stage=dev` when not in use (SSM params are kept; a redeploy creates a **new** Function URL). |

---

## 4. Browser login with pairing

**Status:** done. Released in v1.2.0 (2026-11-16); also in the Pebble app store.

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

### Risks (resolved on the phone) and follow-ups

- `Pebble.openURL` after the async `pair_start` call: works (settings open after the request; slower on a Lambda cold start).
- PKJS keeps polling while the browser is in front: works. Polling also resumes on `ready`.
- Follow-up: polling while settings are open only to change the VIN (up to 200 small requests per open). Add backoff if it matters.
- Follow-up: drop the workaround once [mobileapp#507](https://github.com/coredevices/mobileapp/issues/507) is fixed (keep the in-webview login as the default again).
- `Pebble.webSignIn` is not an option: the store grants the `WebSignIn` capability only to Core Devices' own apps.

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
- [x] Released `v1.2.0` (with `usesPermissions`), GitHub + Pebble app store.
