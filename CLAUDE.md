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
- **Python 3.9-compatible, standard library only, no third-party dependencies** (the system python
  here is 3.9.6 — no `match`, no `X | Y` type syntax). The UI must work at **390px wide** with no
  horizontal page scroll.
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
  median day — never call it a percentage). **Six inputs**: ln-RMSSD HRV, resting HR and hours asleep (naps
  included), each as a **7-day average** (3+ readings) AND as **last night alone** — so last night is half the
  score, not side information. The 7-day scores are compared with the 7-day averages of the 4 weeks before the
  current week and last night with that window's single nights (sample SD, each baseline week 3+ readings),
  RHR flipped, equal weights (Thornton 2019), then standardised against the spread of their own
  earlier composites (`percentile_series`, 28+ days — averaging z-scores shrinks the spread, so the average is
  NOT on a 1-SD scale; the old T scale made above-normal days read as average) and read off the normal curve.
  It sets the day's plan, one session a day as in the trials: **31+ Train as planned** · 7–30 Go easy · <7 Rest
  (`READY_LINES`, = −0.5/−1.5 SD as percentiles; −0.5 SD is the trials' smallest worthwhile change, **−1.5 SD
  is our own extension** — Thornton's "worth acting on" line could not be verified). There is NO answer above the band — no cited trial prescribes a
  harder session for being above it (Kiviniemi 2007 "increase or no change"; Javaloyes 2019 "above or within";
  Vesterinen 2016 "within"; Manresa-Rocamora 2021 "within or above"). The 7-day windows stop the day before
  (`rolling_7`), so last night is counted once, not twice. Rest when the fall is large
  (<7) or sustained — 2nd day in a row below the band (`DAYS_LOW_TO_REST`), never 3 rest days in a row
  (`MAX_REST_DAYS_IN_A_ROW`; Manresa-Rocamora 2021 "low intensity or passive rest"; Plews 2013/Buchheit 2014
  sustained not single-day; rest cap = "will not accumulate more than two consecutive rest sessions",
  Carrasco-Poyatos 2020 — **a trial protocol, not a result**). The 2-day count is **adapted from**
  Kiviniemi 2007 (2 days of decreasing HRV → low intensity or rest): his 2 days are two successive
  DROPS in HRV, not two days below the range, and he never chose between easy and rest — that split is
  ours. Breathing rate is reported, never acted on (Natarajan 2021 gives no numeric rise; the old +3/min
  was ours and never fired). There is **no consecutive-hard-days rule**: Carrasco-Poyatos 2020's protocol caps
  them, but in 531 days only 2 days ever carried a streak of 2 (it counted moderate OR hard days, of which there
  are 40 — consecutive ones are just rare), and the check sat after the band rules so it could only fire on a day
  already scoring 31+; on both those days the score was already below the band — deleted, like breathing. Once any
  session is logged today the pill reads "N sessions logged" and the headline "N sessions logged: matched
  the plan" / "above the plan" (plan spent) unless the plan was Rest. The load ratio
  (`build_acwr` / `build_load_today`) is **reported, never acted on** — it no longer steps the plan down. An
  acute:chronic ratio is a mean over calendar days and this schedule has many zero days, so it swings far harder
  than for the near-daily squads Gabbett's bands came from (above 1.5 on 15.8% of days here; disputed anyway,
  Impellizzeri 2020). It runs on **Edwards TRIMP, never day strain** — Gabbett's bands are linear-load, and the
  strain ratio never passed 1.5 in 568 days.
  `build_training_cost` measures what today's strain costs the NEXT NIGHT's composite (regression on the composite
  z, not the percentile; Newey-West lag 7; gates = significant & negative, monotone across strain terciles, and
  beats doing nothing on a held-out 30%). Outcome AND control are the **standardised** composite z, so the
  coefficient is in the unit it is added to. It is currently **not displayed** — it passes significance and the
  tercile gate (+0.058 / −0.069 / −0.159 on the residualised outcome) but fails the hold-out sign test (53 wins / 60 losses,
  p = 0.77). So the orb keeps the morning score. Tercile gates everywhere sort the RESIDUALISED next-morning z
  (today's z taken out), never the raw one — the fit controls for today, so the gate must too. Do not re-enable it by hand: the `usable` flag decides. The panel's "last night" block is the raw
  values (HRV, resting HR, hours asleep), shown for context — the last-night *scores* are already inside the
  score itself. JP wants ONE score from all measures AND every rule sourced — keep both.
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
- "Today" on the page = the open WHOOP cycle (`snapIsCurrent`), not the calendar date — WHOOP's day runs
  sleep to sleep, so at 1am the previous day is still in progress. Don't compare `snap.date` to the clock.
- Dashboard dates = **the local date the person woke up** (`DayKey`): a cycle is labelled by the end of its
  own night sleep in that sleep's time zone; recovery/sleep/naps follow `cycle_id`; workouts fall into the
  cycle window containing them. Use `record_day(record)`, never `day(created_at)` — WHOOP's day runs sleep
  to sleep, so the UTC day collided on one date here and one day's strain overwrote another.
  `ai_context.py` imports the same key.
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

## Settled decisions (closed by JP — do not reopen)
- **Rest rule:** <7, or 2nd consecutive day below 31, max 2 rest days in a row. Fired over 531 days: large
  fall 21, sustained fall 81, cap 34. Kiviniemi's literal reading was measured and not adopted.
- **Weights:** equal. Variance shares trend 61.6% / last night 38.4%. Not reweighted.
- **Monotony:** two decimals everywhere (1.96 and 2.04 must not both read 2.0).
- **"What moves" gates:** significance, residualised terciles, a one-sided sign test on the 30% hold-out,
  the same sign + p < 0.05 in each half, then a joint refit. The training cost uses the same sign test.

## Independent check
`~/whoop-check/whoop_check.py [dir]` is a SECOND implementation of every displayed number, written
to disagree: it reads the raw export and the built payload and recomputes from scratch, and
deliberately never imports `build_dashboard`. Run it after any change to the maths
(`python3 ~/whoop-check/whoop_check.py .` → 233 checks on real data, 212 on `demo`). It lives
outside the repo, with a copy at `~/Desktop/whoop-check-script.py` — it has been lost twice to
`/tmp` being cleared. When it disagrees, find out which side is wrong before changing either.

## Git
Conventional, descriptive commit messages; small focused commits; push to `main`.
CI (`.github/workflows/ci.yml`) runs tests on Python 3.9/3.12 and builds the macOS app.
