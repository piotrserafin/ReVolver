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

- Access tokens expire after ~60 minutes
- The Pebble JS layer refreshes automatically via the Lambda
- Refresh tokens expire if unused for **7 days**
- Maximum grant lifetime is **6 months** — then re-authenticate

## Hosting

Deployed via GitHub Pages at:

```
https://piotrserafin.github.io/ReVolverAuth/
```

## Security

- **PKCE (S256)** — prevents authorization code interception
- **State parameter** — prevents CSRF attacks
- **No secrets in frontend** — token exchange happens server-side (AWS Lambda)
- **Tokens passed directly to Pebble** — nothing stored on the server

## Lambda Config Contract

The frontend fetches all OAuth config from the Lambda via `GET`. Expected response:

```json
{
  "client_id": "your-volvo-app-client-id",
  "redirect_uri": "https://piotrserafin.github.io/ReVolverAuth/",
  "auth_endpoint": "https://volvoid.eu.volvocars.com/as/authorization.oauth2",
  "scopes": "openid conve:lock conve:unlock ..."
}
```

Token exchange is done via `POST` with `grant_type=authorization_code&code=...&code_verifier=...`.

## References

- [Volvo Authorisation Documentation](https://developer.volvocars.com/apis/docs/authorisation/)
- [PKCE Specification](https://oauth.net/2/pkce/)
