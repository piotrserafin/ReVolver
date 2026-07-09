# ReVolver Token Exchange — AWS CDK Deployment

## Architecture

```
GitHub Pages (public)                AWS Lambda (private)
┌────────────────────────┐          ┌────────────────────────────────┐
│                        │          │                                │
│ "Log in with Volvo ID" │          │  Reads CLIENT_SECRET from      │
│  → Redirect to Volvo   │          │  SSM Parameter Store (KMS      │
│  ← Receive ?code=...   │          │  encrypted, never in code)     │
│                        │──POST──→ │                                │
│  ← tokens             │←─────────│  Exchange code → tokens        │
│  "Return to Pebble"   │          │                                │
└────────────────────────┘          └────────────────────────────────┘
```

## Deploy

### 1. Store secrets in SSM (one time)

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

aws ssm put-parameter \
  --name /revolver/scopes \
  --value "openid conve:vehicle_relation conve:fuel_status conve:odometer_status conve:trip_statistics conve:environment conve:engine_status conve:lock conve:unlock conve:lock_status conve:commands conve:honk_flash conve:climatization_start_stop conve:diagnostics_engine_status conve:diagnostics_workshop conve:doors_status conve:windows_status conve:tyre_status conve:warnings conve:battery_charge_level conve:engine_start_stop conve:navigation conve:command_accessibility" \
  --type String

aws ssm put-parameter \
  --name /revolver/auth-endpoint \
  --value "https://volvoid.eu.volvocars.com/as/authorization.oauth2" \
  --type String

aws ssm put-parameter \
  --name /revolver/token-endpoint \
  --value "https://volvoid.eu.volvocars.com/as/token.oauth2" \
  --type String
```

### 2. Deploy the stack

```bash
cd auth/infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cdk deploy
```

No secrets in the deploy command — they're already in SSM.

### 3. Copy the output URL

```
Outputs:
ReVolverAuthStack.TokenExchangeUrl = https://xxxxxxx.lambda-url.eu-west-1.on.aws/
```

### 4. Update `index.html`

```javascript
var TOKEN_LAMBDA_URL = 'https://xxxxxxx.lambda-url.eu-west-1.on.aws/';
```

Push to GitHub Pages — done!

## Rotate secrets

Just update the SSM parameter — no redeploy needed:

```bash
aws ssm put-parameter \
  --name /revolver/client-secret \
  --value "new-secret" \
  --type SecureString \
  --overwrite
```

The Lambda caches config at cold start. To force reload, touch the function:

```bash
aws lambda update-function-configuration \
  --function-name ReVolverAuthStack-token-exchange \
  --description "force cold start $(date)"
```

## Security

| Concern | Solution |
|---------|----------|
| Secret in git? | ❌ Never — stored in SSM only |
| Secret in CloudFormation? | ❌ Never — Lambda only has `SSM_PREFIX` env var |
| Secret in Lambda console? | ❌ Never — read from SSM at runtime |
| Secret in transit? | ✅ SSM SDK uses HTTPS, KMS decryption |
| Who can read? | Only the Lambda role (IAM scoped to `/revolver/*`) |
| CORS? | Locked to your GitHub Pages origin |
| Audit trail? | CloudTrail logs SSM access |

## Cost

**Free** for personal use:
- Lambda: 1M requests/month free
- Function URL: no cost
- SSM Parameter Store: free for standard parameters
- KMS: free for SSM default key (`aws/ssm`)

## File structure

```
auth/
├── index.html                      ← GitHub Pages (no secrets)
├── server.py                       ← Local full-flow server
├── .env.example
└── infra/                          ← CDK project (same layout as WasteWatch)
    ├── app.py                      ← CDK entry
    ├── cdk.json
    ├── requirements.txt
    ├── test_local.py               ← Local Lambda testing
    ├── lib/
    │   ├── __init__.py
    │   └── revolver_auth_stack.py  ← Stack definition
    └── lambda/
        ├── token_exchange.py       ← Lambda handler (reads SSM)
        └── README.md
```
