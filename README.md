# ReVolver

> **Re**mote **Vol**vo controll**er** — also *volver* (Spanish): "to return/come back" 🔄

Remote control your Volvo from your Pebble smartwatch.

## Features

- ⚡ Flash exterior lights
- 📯 Honk / Honk + Flash
- 🔒 Lock / Unlock doors
- ❄️ Climate on / off
- 🚗 Engine start / stop
- 📊 Live status: lock state, fuel level, model info
- 🔔 Haptic feedback on command result (configurable)
- 🎯 Dynamic command menu (only shows what your car supports)

## Screenshots

```
┌──────────────────┐    ┌──────────────────┐
│    ReVolver      │    │  • Flash Lights  │
│                  │    │    Honk           │
│ YV1LFM1V1T14... │    │    Honk + Flash   │
│   XC60 2024     │    │    Lock           │
│  Locked | 45L   │    │    Unlock         │
│     Ready       │    │                   │
│                  │    │                   │
│ SELECT → commands│    │                   │
└──────────────────┘    └──────────────────┘
    Main Window             ActionMenu
```

## Supported Platforms

- Aplite (Pebble Classic)
- Basalt (Pebble Time)
- Chalk (Pebble Time Round)
- Diorite (Pebble 2)
- Emery (Pebble Time 2)

## How It Works

```
Pebble Watch ←BT→ Phone (PebbleKit JS) ←HTTPS→ Volvo Connected Vehicle API
                         ↕
                   AWS Lambda (OAuth token exchange)
```

1. User authenticates once with Volvo ID (OAuth2 + PKCE)
2. Tokens stored on phone, auto-refreshed when expired
3. Commands sent directly to Volvo API from phone JS
4. Watch displays status and sends command requests over Bluetooth

## Project Layout

```
src/c/ReVolver.c         Watch app (C) — UI, ActionMenu, AppMessage
src/pkjs/index.js        Phone JS — API calls, token management, commands
src/pkjs/config.json     Clay settings page (VIN input, vibration toggle)
infra/                   AWS CDK stack (Lambda token exchange)
  infra/lambda/          Lambda function code
  infra/lib/             CDK stack definition
doc/                     Documentation
  doc/api.md             Volvo API endpoint reference
  doc/auth.md            OAuth2 flow with sequence diagram
  doc/sequences.md       App lifecycle sequence diagrams
  doc/plan.md            Architecture options (auth hosting)
  doc/scopes.md          Volvo OAuth scopes
```

## Building

```bash
pebble build                        # Build for all platforms
pebble install --emulator basalt    # Install on emulator
```

## Setup

### 1. Volvo Developer Account

Register at https://developer.volvocars.com and create an application to get:
- Client ID
- Client Secret
- VCC API Key

### 2. Deploy Auth Backend

```bash
# Store secrets in AWS SSM (one time)
aws ssm put-parameter --name /revolver/client-id --value "..." --type SecureString
aws ssm put-parameter --name /revolver/client-secret --value "..." --type SecureString
aws ssm put-parameter --name /revolver/vcc-api-key --value "..." --type SecureString
aws ssm put-parameter --name /revolver/redirect-uri --value "https://piotrserafin.github.io/ReVolverAuth/" --type String
aws ssm put-parameter --name /revolver/allowed-origins --value "https://piotrserafin.github.io,https://piotrserafin.dev" --type String

# Deploy Lambda
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk deploy
```

### 3. Install on Watch

```bash
pebble build
pebble install --phone <IP>
```

### 4. Configure

1. Open ReVolver settings on phone (Pebble app → ReVolver → Settings)
2. Enter your VIN
3. Click "Log in with Volvo ID"
4. Authenticate with your Volvo ID credentials
5. Done — app shows "Ready"

## Usage

- **SELECT** — Open command menu
- **Pick a command** — Executes immediately, status shows result
- **Vibration** — Single pulse = success, double = error

## Documentation

| Document | Content |
|----------|---------|
| [doc/api.md](doc/api.md) | Volvo API endpoints and response formats |
| [doc/auth.md](doc/auth.md) | OAuth2 authorization flow with sequence diagram |
| [doc/sequences.md](doc/sequences.md) | Full app lifecycle sequence diagrams |
| [doc/plan.md](doc/plan.md) | Architecture options for auth hosting |
| [doc/scopes.md](doc/scopes.md) | Volvo OAuth scopes reference |

## Security

- `client_secret` never leaves AWS (stored in SSM, used by Lambda only)
- OAuth2 PKCE prevents authorization code interception
- VCC API key delivered with tokens (not hardcoded in app)
- All communication over HTTPS
- No secrets in source code or app binary

## License

MIT
