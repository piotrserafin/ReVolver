---
alwaysApply: true
---

## Project Overview

ReVolver — a Pebble smartwatch application that remote-controls a Volvo car via the Volvo Connected Vehicle API. Written in C using the Pebble SDK, with a PebbleKit JS layer for Bluetooth communication and OAuth2 token management.

## Supported Platforms

The app targets multiple Pebble watch models:
- aplite (Pebble classic)
- basalt (Pebble Time)
- chalk (Pebble Time Round)
- diorite (Pebble 2)
- emery (Pebble Time 2)

## Commands

```bash
# Build the app for all platforms
pebble build

# Clean build artifacts
pebble clean

# Install the app on specific emulator
pebble install --emulator basalt

# Screenshot the running emulator
pebble screenshot --scale 6 --no-open screenshot.png
```

If you need more information on the `pebble` command or a sub-command, append `--help`.

### Headless Environments

If you're running in an environment without a window server (e.g., headless Linux, Docker, CI), you must add `--vnc` to **all commands that interact with the emulator**. This includes app installs, screenshots, button presses, and any `emu-*` commands:

```bash
pebble install --emulator basalt --vnc
pebble screenshot --vnc --scale 6 --no-open screenshot.png
pebble emu-button --emulator basalt --vnc click select
```

The `--vnc` flag enables a VNC-based display backend that doesn't require X11.

## Project Structure

```
src/c/           - C source files for the watchapp
src/pkjs/        - PebbleKitJS files (OAuth token management, Volvo API calls)
doc/             - Documentation (scopes, architecture notes, API reference)
infra/           - AWS CDK stack (Lambda token exchange proxy)
  infra/lambda/  - Lambda function code
  infra/lib/     - CDK stack definition
```

## App Flow

See `doc/sequences.md` for detailed sequence diagrams covering:
- First launch (no tokens → settings → OAuth → ready)
- Subsequent launch (cached data + token refresh)
- Command execution (normal + 401 retry)

## App Architecture

### Main Window
- Title: "ReVolver"
- VIN (24pt bold)
- Car info: model + year (18pt, cached from API)
- Car status: lock state + fuel level (18pt bold, green on color watches)
- Connection status (24pt bold): "Ready", "Car offline", "Open settings"
- Hint: "SELECT → commands"

### ActionMenu (triggered by SELECT button)
- Dynamic list of commands based on vehicle capabilities
- Commands fetched from `/vehicles/{vin}/commands` and cached
- Bitmask sent to watch to filter available items
- Blue background on color watches

### Command Flow
```
SELECT → ActionMenu → pick command → status shows "Sending..."
→ JS calls Volvo API → result shown temporarily (3s) + vibration
→ status reverts to "Ready"
```

### Vibration Feedback (configurable via Clay settings)
- Success: single short pulse (100ms)
- Error: double pulse (100ms-100ms-100ms)
- Result text prefixed with `+` (success) or `-` (error)

## Message Keys

| Key | ID | Direction | Type | Purpose |
|-----|----|-----------|------|---------|
| `VIN` | 10000 | JS → Watch | string | Vehicle VIN |
| `STATUS_MSG` | 10001 | JS → Watch | string | Connection status |
| `COMMAND` | 10002 | Watch → JS | string | Command to execute (e.g., "flash") |
| `COMMAND_RESULT` | 10003 | JS → Watch | string | `+text` or `-text` (prefix = success/error) |
| `VIBRATE` | 10004 | JS → Watch | int | Settings: 1=on, 0=off. Persisted on watch. |
| `CAR_STATUS` | 10005 | JS → Watch | string | Live car state ("Locked \| 45L") |
| `CAR_INFO` | 10006 | JS → Watch | string | Model + year ("XC60 2024"). Cached. |
| `AVAILABLE_CMDS` | 10007 | JS → Watch | int | Bitmask of supported commands |

### Command Bit Flags

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

The app uses a secure OAuth2 PKCE flow with Volvo ID.

**Current:** GitHub Pages frontend (`ReVolverAuth` repo) + Lambda token exchange proxy.

**Planned:** Lambda-only architecture — see `doc/plan.md`.

### SSM Parameters (`/revolver` prefix)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `/revolver/client-id` | SecureString | ✅ | Volvo app client ID |
| `/revolver/client-secret` | SecureString | ✅ | Volvo app client secret |
| `/revolver/vcc-api-key` | SecureString | ✅ | Volvo Connected Cars API key |
| `/revolver/redirect-uri` | String | ✅ | `https://piotrserafin.github.io/ReVolverAuth/` |
| `/revolver/allowed-origins` | String | ✅ | Comma-separated origins |
| `/revolver/scopes` | String | Optional | Space-separated OAuth scopes |
| `/revolver/auth-endpoint` | String | Optional | Volvo authorization URL |
| `/revolver/token-endpoint` | String | Optional | Volvo token URL |

### Token Refresh

- Auto-refresh on launch if token expires in < 60s or API key missing
- Auto-refresh before each command if expired
- Retry on 401 from Volvo (refresh + retry once)
- Refresh lock prevents concurrent requests (Volvo refresh tokens are single-use)
- Lambda returns `vcc_api_key` alongside tokens (fetched on every refresh)

### Key URLs

- Auth frontend: `https://piotrserafin.github.io/ReVolverAuth/`
- Volvo auth: `https://volvoid.eu.volvocars.com/as/authorization.oauth2`
- Volvo token: `https://volvoid.eu.volvocars.com/as/token.oauth2`
- Volvo API: `https://api.volvocars.com/connected-vehicle/v2`
- Lambda: `https://tpl5qhrn75bxzps77pdqllhxuy0mckgw.lambda-url.eu-central-1.on.aws/`

### Deploy Commands

```bash
aws ssm put-parameter --name /revolver/client-id --value "..." --type SecureString
aws ssm put-parameter --name /revolver/client-secret --value "..." --type SecureString
aws ssm put-parameter --name /revolver/vcc-api-key --value "..." --type SecureString
aws ssm put-parameter --name /revolver/redirect-uri --value "https://piotrserafin.github.io/ReVolverAuth/" --type String
aws ssm put-parameter --name /revolver/allowed-origins --value "https://piotrserafin.github.io,https://piotrserafin.dev" --type String

cd infra && source .venv/bin/activate && cdk deploy
```

## Volvo Connected Vehicle API

Documentation: https://developer.volvocars.com/apis/

See `doc/api.md` for full endpoint reference.

### API Calls on Launch

1. `GET /vehicles/{vin}/command-accessibility` — is car online?
2. `GET /vehicles/{vin}/commands` — available commands (cached)
3. `GET /vehicles/{vin}` — model, year (cached)
4. `GET /vehicles/{vin}/doors` — lock status
5. `GET /vehicles/{vin}/fuel` — fuel level

### Cached Data (localStorage)

| Key | Fetched From | Cache Policy |
|-----|-------------|--------------|
| `revolver_car_info` | `/vehicles/{vin}` | Fetched once, never changes |
| `revolver_commands` | `/vehicles/{vin}/commands` | Fetched once, never changes |
| Access/refresh tokens | Lambda | Refreshed when expired |

## Known Issues

- Clay returns numeric message keys on real hardware — use `require('message_keys')` for lookup
- `setTimeout` in PebbleKit JS may be killed by phone OS — avoid for critical sends
- AppMessage requires queue pattern (only one message in flight at a time)
- Sideloading clears PebbleKit JS localStorage — requires re-login during development
- Volvo access tokens last ~5 min; refresh threshold is 60s before expiry

## Configuration

The app is configured as a watchapp (not a watchface): `"watchface": false` in `package.json`.

## SDK Documentation

The full Pebble SDK documentation is available at https://developer.repebble.com.

An index of every page is at https://developer.repebble.com/llms.txt. Use it to discover what's available. Every page also has a Markdown version: append `.md` to any documentation URL to fetch plain Markdown instead of HTML (e.g. `https://developer.repebble.com/guides/events-and-services/buttons.md`). Prefer the `.md` form when reading docs.

Key Entry Points:
- https://developer.repebble.com/tutorials/watchface-tutorial/part1 - C development start
- https://developer.repebble.com/guides/events-and-services/buttons - Button handling
- https://developer.repebble.com/guides/user-interfaces/layers - UI foundations
- https://developer.repebble.com/docs/c/User_Interface/Window/ActionMenu/index - ActionMenu API

## Development Best Practices

- Whenever making changes, run `pebble screenshot --scale 6` and view the screenshot to make sure it's what the user requested. If not, make more changes until it does what it's supposed to.

## Emulator Button Control

Control emulator buttons programmatically with `pebble emu-button`:

```bash
pebble emu-button click select          # Normal click
pebble emu-button click back --duration 2000  # Long press
pebble emu-button click down --repeat 5  # Scroll
```

**Buttons:** `back`, `up`, `select`, `down`

## AI Interaction Guidelines

- **NEVER execute destructive or side-effecting actions without explicit user confirmation.** This includes: `cdk deploy`, `git commit`, `git push`, `aws ssm put-parameter`, `pebble install`, or any command that modifies remote state.
- **Ask before making code changes.** If the user asks for modifications, describe the planned changes and wait for approval before editing files.
- Only read files, run builds (`pebble build`), run `cdk synth`, and take screenshots without asking.
- When given an image of a watchface to replicate, describe the target watchface in precise detail. Note every visual element present, as well as size, alignment, font weight, spacing, and location.

## AI Code Review Guidelines

- Once you think you've fulfilled the user's request, ask yourself if you see any issues with the current screenshot, and if there are any differences between the screenshot and the reference image or the user's description. If so, fix them.
