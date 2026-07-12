---
alwaysApply: true
---

## Project Overview

ReVolver — **Re**mote **Vol**vo controll**er**. A Pebble smartwatch application that remote-controls a Volvo car via the Volvo Connected Vehicle API. Written in C using the Pebble SDK, with a PebbleKit JS layer for Bluetooth communication and OAuth2 token management.

## Supported Platforms

- aplite (Pebble Classic)
- basalt (Pebble Time)
- chalk (Pebble Time Round)
- diorite (Pebble 2)
- emery (Pebble Time 2)

## Commands

```bash
pebble build                             # Build for all platforms
pebble clean                             # Clean build artifacts
pebble install --emulator basalt         # Install on emulator
pebble screenshot --scale 6 --no-open screenshot.png  # Screenshot
```

If you need more information on the `pebble` command or a sub-command, append `--help`.

### Headless Environments

Add `--vnc` to all emulator commands (installs, screenshots, button presses):

```bash
pebble install --emulator basalt --vnc
pebble screenshot --vnc --scale 6 --no-open screenshot.png
pebble emu-button --emulator basalt --vnc click select
```

## Project Structure

```
src/c/
  main.c                    - Init, event loop
  modules/
    messaging.h/.c          - AppMessage handlers, vibration
    commands.h/.c           - Command table, bitmask, ActionMenu
  windows/
    main_window.h/.c        - Main window UI, persisted display data
src/pkjs/
  index.js                  - Volvo API, token management, command execution
  config.json               - Clay settings (VIN, vibration toggle)
doc/
  api.md                    - Volvo API endpoint reference
  auth.md                   - OAuth2 flow with sequence diagram
  sequences.md              - App lifecycle sequence diagrams
  plan.md                   - Auth hosting architecture options
  scopes.md                 - Volvo OAuth scopes
infra/
  lambda/token_exchange.py  - Lambda handler (OAuth proxy)
  lambda/README.md          - Lambda documentation
  lib/revolver_auth_stack.py - CDK stack definition
  app.py                    - CDK entry point
```

## App Flow

See `doc/sequences.md` for detailed sequence diagrams covering:
- First launch (no tokens → settings → OAuth → ready)
- Subsequent launch (cached data + token refresh)
- Command execution (normal + 401 retry)

## App Architecture

### Main Window
- Title: "ReVolver" (28pt bold)
- VIN (24pt bold) — persisted on watch
- Car info: model + year (18pt) — persisted on watch
- Car status: lock state + fuel level (18pt bold, green) — persisted on watch
- Connection status (24pt bold): "Ready", "Car offline", "Connecting...", "Refreshing..."
- Hint: "SELECT → commands"
- **UP button** — manual refresh of car status

### ActionMenu (triggered by SELECT button)
- Dynamic list based on vehicle capabilities (bitmask from `/commands` API)
- Confirmation sub-menu for Unlock and Engine Start
- Engine Start: time selection (1/5/10/15 min) → Confirm
- Blue background on color watches (GColorCobaltBlue)

### Command Flow
```
SELECT → ActionMenu → pick command → status shows "Sending..."
→ JS calls Volvo API → friendly result (e.g., "Locked!") shown 3s + vibration
→ status reverts to "Ready"
```

### Vibration Feedback (configurable via Clay)
- Success: single short pulse (100ms)
- Error: double pulse (100ms-100ms-100ms)
- Result text prefixed with `+` (success) or `-` (error) in AppMessage

### Persisted Watch Data
VIN, car info, and car status are persisted on watch flash storage — displayed immediately on launch with no "Not set" flash.

## JS Command Registry

Single `COMMANDS` object holds all command metadata (mirrors C-side `COMMANDS[]` array):

```js
var COMMANDS = {
  'flash':          { bit: 0x01, success: 'Flashed!' },
  'honk':           { bit: 0x02, success: 'Honked!' },
  'lock':           { bit: 0x08, success: 'Locked!' },
  'unlock':         { bit: 0x10, success: 'Unlocked!' },
  'engine-start':   { bit: 0x80, success: 'Started!',
    body: function(p) { return JSON.stringify({runtimeMinutes: parseInt(p, 10)}); }
  },
  ...
};
```

## Message Keys

| Key | ID | Direction | Type | Purpose |
|-----|----|-----------|------|---------|
| `VIN` | 10000 | JS → Watch | string | Vehicle VIN |
| `STATUS_MSG` | 10001 | JS → Watch | string | Connection status |
| `COMMAND` | 10002 | Watch → JS | string | Command to execute (e.g., "flash", "engine-start:10", "refresh") |
| `COMMAND_RESULT` | 10003 | JS → Watch | string | `+text` or `-text` (prefix = success/error) |
| `VIBRATE` | 10004 | JS → Watch | int | Settings: 1=on, 0=off. Persisted on watch. |
| `CAR_STATUS` | 10005 | JS → Watch | string | Live car state ("Locked \| 45L") |
| `CAR_INFO` | 10006 | JS → Watch | string | Model + year ("XC60 2024"). Cached. |
| `AVAILABLE_CMDS` | 10007 | JS → Watch | int | Bitmask of supported commands |

### Command Bit Flags (C defines, must match JS COMMANDS[].bit)

```c
#define CMD_FLASH         (1 << 0)  // 0x01
#define CMD_HONK          (1 << 1)  // 0x02
#define CMD_HONK_FLASH    (1 << 2)  // 0x04
#define CMD_LOCK          (1 << 3)  // 0x08
#define CMD_UNLOCK        (1 << 4)  // 0x10
#define CMD_CLIMATE_START (1 << 5)  // 0x20
#define CMD_CLIMATE_STOP  (1 << 6)  // 0x40
#define CMD_ENGINE_START  (1 << 7)  // 0x80
#define CMD_ENGINE_STOP   (1 << 8)  // 0x100
```

## Auth Architecture

OAuth2 PKCE flow with Volvo ID. Lambda required because Volvo needs both PKCE AND `client_secret`.

See `doc/auth.md` for full sequence diagram and `infra/lambda/README.md` for why Lambda is required.

**Current:** GitHub Pages frontend (`ReVolverAuth` repo) + Lambda proxy.

**Planned:** Lambda-only — see `doc/plan.md`.

### SSM Parameters (`/revolver` prefix)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `/revolver/client-id` | SecureString | ✅ | Volvo app client ID |
| `/revolver/client-secret` | SecureString | ✅ | Volvo app client secret |
| `/revolver/vcc-api-key` | SecureString | ✅ | Volvo Connected Cars API key |
| `/revolver/redirect-uri` | String | ✅ | OAuth redirect URI |
| `/revolver/allowed-origins` | String | ✅ | Comma-separated CORS origins |
| `/revolver/scopes` | String | Optional | OAuth scopes |
| `/revolver/auth-endpoint` | String | Optional | Volvo auth URL |
| `/revolver/token-endpoint` | String | Optional | Volvo token URL |

### Token Refresh

- Auto-refresh on launch if token expires in < 60s or API key missing
- Auto-refresh before each command if expired
- Retry on 401 from Volvo (refresh + retry once)
- Refresh lock prevents concurrent requests (Volvo refresh tokens are single-use)
- Lambda returns `vcc_api_key` alongside tokens

### Key URLs

- Auth frontend: `https://piotrserafin.github.io/ReVolverAuth/`
- Volvo API: `https://api.volvocars.com/connected-vehicle/v2`
- Lambda: `https://tpl5qhrn75bxzps77pdqllhxuy0mckgw.lambda-url.eu-central-1.on.aws/`

## Volvo Connected Vehicle API

See `doc/api.md` for full endpoint reference.

### API Calls on Launch

1. `GET /vehicles/{vin}/command-accessibility` — is car online?
2. `GET /vehicles/{vin}/commands` — available commands (cached, sent as bitmask)
3. `GET /vehicles/{vin}` — model, year (cached)
4. `GET /vehicles/{vin}/doors` — lock status
5. `GET /vehicles/{vin}/fuel` — fuel level

### Cached Data

| Storage | Data | Cache Policy |
|---------|------|-------------|
| JS localStorage | `car_info`, `commands`, tokens | Cleared on VIN change or re-login |
| Watch persist | VIN, car info, car status | Updated on every message, instant on launch |

## Known Issues

- Clay returns numeric message keys on real hardware — use `require('message_keys')` for lookup
- `setTimeout` in PebbleKit JS may be killed by phone OS — avoid for critical sends
- AppMessage requires queue pattern (only one message in flight at a time)
- Sideloading clears PebbleKit JS localStorage — requires re-login during development
- Volvo access tokens last ~5 min; refresh threshold is 60s before expiry
- Investigating: occasional re-login needed after ~1h idle (diagnostic logs in place)

## Configuration

Watchapp (not watchface): `"watchface": false` in `package.json`.

## SDK Documentation

Full Pebble SDK docs: https://developer.repebble.com (append `.md` for Markdown version).

Index: https://developer.repebble.com/llms.txt

Key references:
- https://developer.repebble.com/docs/c/User_Interface/Window/ActionMenu/index — ActionMenu API
- https://developer.repebble.com/guides/best-practices/modular-app-architecture — Modular architecture

## Emulator Button Control

```bash
pebble emu-button click select                    # Normal click
pebble emu-button click back --duration 2000      # Long press
pebble emu-button click down --repeat 5           # Scroll
```

**Buttons:** `back`, `up` (refresh), `select` (commands), `down`

## AI Interaction Guidelines

- **NEVER execute destructive or side-effecting actions without explicit user confirmation.** This includes: `cdk deploy`, `git commit`, `git push`, `aws ssm put-parameter`, `pebble install`, or any command that modifies remote state.
- **Ask before making code changes.** If the user asks for modifications, describe the planned changes and wait for approval before editing files.
- Only read files, run builds (`pebble build`), run `cdk synth`, and take screenshots without asking.

## AI Code Review Guidelines

- Once you think you've fulfilled the user's request, ask yourself if you see any issues with the current screenshot, and if there are any differences between the screenshot and the reference image or the user's description. If so, fix them.
