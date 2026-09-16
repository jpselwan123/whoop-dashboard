# Security

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) on this repository
instead, and include steps to reproduce. You'll get a response as soon as possible.

## How this project handles secrets and data

- All credentials (WHOOP client secret, OAuth tokens, AI provider keys) live only in
  local files that are git-ignored: `.env` and `whoop_tokens.json`.
- API keys are read server-side by `chat_server.py` and are never sent to the page.
- The local server binds to `127.0.0.1` only and is not reachable from other devices.
- Health data stays on your machine, except what the optional chat sends to the AI
  provider you configure — see "What the chat sends" in the README.

If you fork this project, never commit `.env`, `whoop_tokens.json`, or any of the
generated data files listed in `.gitignore`.
