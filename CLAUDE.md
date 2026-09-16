# CLAUDE.md — WHOOP Dashboard

Guide for AI coding agents (and humans) working in this repo. Personal/local notes
live in `CLAUDE.local.md` (git-ignored). Read both before changing anything.

## What this is
Local-first dashboard over one person's WHOOP data (API v2): Python stdlib pipeline →
static `index.html`, a local server (`chat_server.py`, 127.0.0.1:8934) for refresh +
AI chat, and a Swift/WebKit macOS wrapper. Zero third-party dependencies — keep it so.

## Commands
```bash
./refresh.sh                                        # pull WHOOP + rebuild (real data)
python3 build_dashboard.py [dir]                    # rebuild only (default: .)
python3 scripts/generate_demo_data.py demo && python3 build_dashboard.py demo   # synthetic
python3 -m unittest discover -s tests -t tests      # tests (no network, no keys)
python3 scripts/privacy_scan.py [--staged]          # must be clean before any push
./native_app/build.sh                               # compile the macOS app
```

## Map
| File | Role |
|---|---|
| `whoop.py` | OAuth (refresh tokens rotate — write before use), incremental sync (10-day lookback), `--auth-url` |
| `build_dashboard.py` | every computed metric → `dashboard_data.json`; injects JSON into template at `__DATA__` |
| `dashboard_template.html` | whole UI: CSS tokens on `:root`, vanilla JS, hand-built SVG charts; `renderAll()` calls each `renderX()` |
| `chat_server.py` | `/ask` (OpenAI Responses API default, Anthropic optional), `/refresh`, `/data`; `.env` re-read per request |
| `ai_context.py` | full history → compact pipe tables for the model; never includes email/last name/ids |
| `env_config.py` | `.env` loader, `atomic_write` (temp + `os.replace`) — use for every data write |
| `scripts/generate_demo_data.py` | synthetic athlete "Alex" (seed 23) for demo, tests, screenshots |
| `native_app/main.swift` | runs `refresh.sh`, loads `~/whoop/index.html`, spawns `chat_server.py` |

## Hard rules
- **Privacy first.** Never commit `.env`, `whoop_tokens.json`, `whoop_data.json`,
  `dashboard_data.json`, `index.html`. Tests/screenshots/docs use synthetic data only.
  No personal names, emails, ids, or `/Users/...` paths in tracked files.
- **API keys stay server-side** — never sent to the page, never logged, never pasted into chat.
- **Never break the page.** Every render path must survive empty/new accounts, missing
  optional fields (`spo2`, `respiratory_rate`), zero workouts. A thrown error in one
  `renderX()` kills everything after it in `renderAll()` — guard, don't assume.
- **Visibility is never JS-gated.** Animations must fail open (content visible if JS breaks).
- **Nothing automatic.** No timers/auto-refresh; data refreshes only via the button.
- **Readiness is the answer.** One number (how ready to train today) → Push 63+ · Train 38–62 ·
  Go easy 25–37 · Rest <25 (`READY_BANDS`). Context only *lowers* it via caps (`READY_CAPS`: warning
  sign must be *confirmed* by `build_warning` — 2 of last 3 nights or 2+ vitals, still out last night — and caps
  37→24 graded; one-off nights are only "watching"; trained hard today / overload week ≤37) — never an "override" or a second verdict label.
  One explanation panel (orb or How? ›).
- **Readiness ≠ recovery.** Readiness (`build_readiness` in build_dashboard.py) = 7-day ln-RMSSD
  HRV + 7-day resting HR + 3-night sleep, each vs a 60-day personal baseline (±0.5 SD SWC), equal
  weights, 50 = normal (the body-trend score). No sliders. Changes to the model need a cited source and tests
  (`tests/test_readiness.py`); recovery keeps WHOOP zones 34/67.
- Add a test for new metrics or server behavior; run tests + privacy scan before pushing.

## UI / product conventions
- **Clean beats dense.** One number + one signal per stat; no mini-charts under numbers
  (trends belong in the Trend explorer). When in doubt, remove.
- **Data first, few words.** Show numbers with their thresholds/ranges ("9 / 7+"), not prose.
  No statistics jargon in the UI (no z-scores, "SD") — convert to plain units/limits.
- Details open on **click**, not hover (must work on touch).
- Weeks are ISO **Mon–Sun**; partial current week/month is faded, gaps shown not hidden.
- Date ranges formatted like `24–30 Aug`; no "1 wk ago" labels.
- Flat zone colors: recovery red 0–33 `--critical`, yellow 34–66 `--warn`, green 67–100 `--good`.
- Metrics not in the WHOOP app get the `Beyond WHOOP` badge.
- Fonts: Archivo (headings), IBM Plex Sans (body), IBM Plex Mono (numbers). Dark theme tokens
  on `:root` — reuse them, don't hardcode colors.
- Must work at 390px wide with no horizontal page scroll; respect `prefers-reduced-motion`.

## Gotchas (learned the hard way)
- WKWebView blocks `fetch()` of `file://` → the page gets fresh data from `GET /data`.
- macOS ATS blocks `http://127.0.0.1` without `NSAllowsLocalNetworking` in Info.plist ("Load failed").
- Don't step `Date` objects day-by-day across DST (hour drift); compare `YYYY-MM-DD` strings.
- Dashboard dates = UTC calendar day of `created_at`; `ai_context.py` matches that convention.
- Heatmap/month labels collide on partial months — drop the older label when < 3 cells apart.
- OpenAI long-context pricing doubles above 272K input tokens; the AI context is ~40–60K.

## Git
Conventional, descriptive commit messages; small focused commits; push to `main`.
CI (`.github/workflows/ci.yml`) runs tests on Python 3.9/3.12 and builds the macOS app.
