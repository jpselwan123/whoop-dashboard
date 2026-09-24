# Security

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) on this repository
instead, and include steps to reproduce. You'll get a response as soon as possible.

## How this project handles secrets and data

- All credentials (WHOOP client secret, OAuth tokens, AI provider keys) live only in
  local files that are git-ignored: `.env` and `whoop_tokens.json`.
- API keys are read server-side by `chat_server.py` and are never sent to the page.
- The local server binds to `127.0.0.1` only and is not reachable from other devices. **That alone is not
  enough**: any web page open in a browser on the same Mac can send requests to `127.0.0.1`. So every
  request must also carry a **per-run token** (`X-Dashboard-Token`). The server mints it with
  `secrets.token_urlsafe` each time it starts, writes it to the git-ignored `.dashboard_token` (mode 0600),
  and injects it into the generated `index.html`; anything without the matching token — compared with
  `hmac.compare_digest` — gets `403` before any work is done, on `/data`, `/ask` and `/refresh` alike.
  **This is what stops other local pages reading your data, spending your AI credits or triggering a
  refresh.**
- There is no `Access-Control-Allow-Origin: *`. The only CORS header sent is
  `Access-Control-Allow-Origin: null`, and only to requests whose Origin is `null` — which is what the
  `file://` page sends. Origin is deliberately not the security check (a sandboxed iframe on any site also
  sends `null`); the token is. A request without it can read nothing but a `403`.
- Requests whose `Host` header is not `127.0.0.1:8934` or `localhost:8934` are refused, which blocks DNS
  rebinding (a hostile hostname that resolves to `127.0.0.1`).
- Demo builds never contain the token: they are meant to be shared and have no server to talk to.
- Health data stays on your machine, except what the optional chat sends to the AI
  provider you configure — see "What the chat sends" in the README.

If you fork this project, never commit `.env`, `whoop_tokens.json`, or any of the
generated data files listed in `.gitignore`.
