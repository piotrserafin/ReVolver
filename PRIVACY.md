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
adds the secret to your login request and forwards it to Volvo. It does not log
or inspect your tokens. During browser login it holds them briefly until your
phone collects them (see below).

## What stays on your phone

| Data | Location |
|------|----------|
| Access token | Phone (PebbleKit JS) |
| Refresh token | Phone (PebbleKit JS) |
| VIN | Phone + watch |
| Car status | Phone + watch |

Tokens are not kept on any server. When you log in inside the Pebble app's
settings page, they pass through the Lambda in transit and go straight to your
phone.

**Browser login.** On Android, Volvo's login page doesn't work inside the Pebble
app ([reported to the Pebble app developers](https://github.com/coredevices/mobileapp/issues/507)), so ReVolver opens it in your
phone's browser. The browser can't hand the
tokens back to the Pebble app directly, so the Lambda keeps them in an encrypted
AWS DynamoDB table until the ReVolver app on your phone collects them, usually
within seconds:

- Deleted as soon as they're collected, and never kept longer than 10 minutes
- Only the ReVolver app that started the login can collect them (it holds a
  one-time secret that never leaves your phone)
- The browser never receives your tokens

## What the Lambda proxy sees

During login and token refresh, your tokens briefly pass through the proxy
(and, for browser login, wait for your phone as described above).
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
