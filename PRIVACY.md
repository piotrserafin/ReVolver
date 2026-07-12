# Privacy & Security

## How authentication works

ReVolver uses the official Volvo ID OAuth2 flow to access your car. You log in
directly with Volvo — the app never sees your Volvo ID password.

## Why there's a server component

OAuth2 supports a **public client** flow (PKCE only) where no server-side
secret is needed — the entire token exchange happens on-device. Unfortunately,
Volvo's API does not support this. It requires a **client secret** alongside
PKCE for every token exchange and refresh.

This secret cannot be embedded in the app — a `.pbw` file is a simple zip
archive and anyone could extract it.

Instead, the secret is stored securely on a minimal AWS Lambda proxy. The proxy
does one thing: it adds the secret to your login request and forwards it to
Volvo. It does not store, log, or inspect your tokens.

## What stays on your phone

| Data | Location |
|------|----------|
| Access token | Phone (PebbleKit JS) |
| Refresh token | Phone (PebbleKit JS) |
| VIN | Phone + watch |
| Car status | Phone + watch |

Tokens never touch a database. They pass through the Lambda in transit and are
returned directly to your phone.

## What the Lambda proxy sees

During login and token refresh, your tokens briefly pass through the proxy.
This is the same architecture used by every third-party car app (Tesla,
BMW, etc.) that requires a server-side secret.

## Open source

Both the app and the Lambda proxy are fully open source. You can inspect
exactly what the server does:

- [App code](https://github.com/piotrserafin/ReVolver)
- [Lambda code](https://github.com/piotrserafin/ReVolver/tree/main/infra/lambda)

## Your controls

- You can revoke access at any time from your
  [Volvo ID account settings](https://volvoid.eu.volvocars.com)
- Tokens expire automatically (~5 minutes for access, 7 days for refresh)
- No data is shared with third parties
