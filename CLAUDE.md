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
- **Every rule and threshold must come from published research** (JP's rule). No invented cut-offs,
  weights or minute counts. Where papers are ambiguous, follow the method paper they cite and note it in
  the README; where no study defines something, show a plain fact instead (e.g. rest day = last day
  without a workout). Statistical comparisons use Welch's t-test, p < 0.05, 30+ per group.
- **Readiness** (`build_readiness`) = one 0–100 score, a **percentile of the person's own days** (50 = their
  median day — never call it a percentage): 7-day ln-RMSSD HRV, resting HR and hours asleep (3+ readings)
  each a standard score vs the 7-day averages of the 4 weeks before the current week (sample SD, each week
  3+ readings), RHR flipped, equal weights (Thornton 2019), then standardised against the spread of their own
  earlier composites (`percentile_series`, 28+ days — averaging z-scores shrinks the spread, so the average is
  NOT on a 1-SD scale; the old T scale made above-normal days read as average) and read off the normal curve.
  It sets the day's plan, one session a day as in the trials: 69+ Train hard · 31–68 Train as planned ·
  below the band Go easy or Rest (`READY_LINES`, = +0.5/−0.5/−1.5 SD as percentiles). Rest when the fall is large
  (<7) or sustained — 3rd day in a row below the band (`DAYS_LOW_TO_REST`), never 3 rest days in a row
  (`MAX_REST_DAYS_IN_A_ROW`; Manresa-Rocamora 2021 "low intensity or passive rest"; Plews 2013/Buchheit 2014
  sustained not single-day; Kiviniemi 2007 caps consecutive rest days). Rest on breathing +3/min; Go easy after 2 hard days in a row. Once any session is
  logged today the page shows "Done for today" (plan spent) unless the plan was Rest. Last night is information only. JP wants ONE score from all
  measures AND every rule sourced — keep both.
- **Intensity** = Seiler zones (82% / 87% of max HR) converted from WHOOP heart-rate-reserve zones
  (`intensity_minutes`, proportional split); session level = where most time was. Strength sessions: none.
- Recovery keeps WHOOP zones 34/67. No sliders. Model changes need a cited source and tests.
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
- WHOOP `sleep_performance_percentage` = hours vs needed only until ~Oct 2025; after that it's WHOOP's blended
  score. The WHOOP app rounds sleep stages on the running total (light → deep → REM → awake) — `ai_context._stage_minutes`.
- `whoop_data.json` lists are newest-first — sort before taking "latest".
- Every rolling window is **calendar days**, never "last N records" (`_calendar_window`, `lastDays` in the
  template) — the real export has a 7-month gap (Mar–Oct 2025). Weekly charts keep empty weeks as gaps.
- Easy/moderate/hard = Seiler zones everywhere (zone chart, session view, readiness), via `intensity_minutes`.
- Sports are compared only within the same intensity (`build_sport_recovery_cost`), every sport listed; never
  recommend a specific sport. WHOOP strain is logarithmic — never add it across sessions (use Edwards TRIMP). Strength sessions are out of the zone split.
- UI rules from the revision brief: no formulas/stat notation in the UI, net element count must not grow,
  never shrink spacing to fit, one idea per card, no new colors.
- OpenAI long-context pricing doubles above 272K input tokens; the AI context is ~40–60K.

## Git
Conventional, descriptive commit messages; small focused commits; push to `main`.
CI (`.github/workflows/ci.yml`) runs tests on Python 3.9/3.12 and builds the macOS app.
