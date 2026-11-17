# ReVolver Auth

Authentication page for ReVolver — a Volvo Connected Vehicle remote control for Pebble smartwatches.

## What you need

- A **Volvo ID** (the account you use in the Volvo Cars app)

That's it. Just click "Log in with Volvo ID", sign in, and you're connected.

## How it works

1. You click **"Log in with Volvo ID"**
2. You're redirected to Volvo's secure login page
3. You sign in with your Volvo ID and approve access
4. You're redirected back with your tokens
5. Tap **"Return to Pebble"** to send credentials to the watch

The token exchange is handled by a backend Lambda — no secrets are exposed in this page.

## Token Refresh

- The Pebble JS layer refreshes automatically via the Lambda
- Access tokens expire after **~5 minutes**
- Refresh tokens are single-use (replaced on every refresh) and expire if unused for a long time — then log in again

## Hosting

Deployed via GitHub Pages at:

```
https://piotrserafin.github.io/ReVolverAuth/
```

## Security

- **PKCE (S256)** — prevents authorization code interception
- **State parameter** — prevents CSRF attacks
- **No secrets in frontend** — token exchange happens server-side (AWS Lambda)
- **Tokens passed directly to Pebble** — or, with browser login, held by the Lambda for at most 10 minutes (encrypted, single use) until PebbleKit JS collects them

## Lambda Config Contract

The frontend fetches all OAuth config from the Lambda via `GET`. Expected response:

```json
{
  "client_id": "your-volvo-app-client-id",
  "redirect_uri": "https://piotrserafin.github.io/ReVolverAuth/",
  "auth_endpoint": "https://auth.volvocars.com/realms/volvocars/protocol/openid-connect/auth",
  "scopes": "openid conve:lock conve:unlock ..."
}
```

Token exchange is done via `POST` with `grant_type=authorization_code&code=...&code_verifier=...`.

## References

- [Volvo Authorisation Documentation](https://developer.volvocars.com/apis/docs/authorisation/)
- [PKCE Specification](https://oauth.net/2/pkce/)
