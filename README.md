<div align="center">

<img src="native_app/icon_1024.png" width="112" alt="WHOOP Dashboard icon">

# WHOOP Dashboard

**A private, data-first training dashboard built on your own WHOOP data.**
Sports-science metrics the WHOOP app doesn't show, a daily training call you can
check line by line, and an AI chat that knows your entire history.

[![CI](https://github.com/jpselwan123/whoop-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/jpselwan123/whoop-dashboard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![macOS](https://img.shields.io/badge/app-macOS%2011%2B-000000?logo=apple&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

<img src="docs/screenshots/overview.png" alt="Daily view: training call, readiness orb with last night and recent week, recovery, strain, sleep" width="880">

<sub>All screenshots use the built-in synthetic demo athlete — no real health data.</sub>

</div>

---

## Contents

- [Why this exists](#why-this-exists)
- [Features](#features)
- [Try it in 30 seconds (no WHOOP needed)](#try-it-in-30-seconds-no-whoop-needed)
- [Setup with your WHOOP](#setup-with-your-whoop)
- [AI chat](#ai-chat)
- [How the numbers work](#how-the-numbers-work)
- [Architecture](#architecture)
- [Privacy & security](#privacy--security)
- [Development](#development)
- [Limitations](#limitations)
- [License & disclaimer](#license--disclaimer)

## Why this exists

The WHOOP app tells you *what* your recovery and strain are. It doesn't tell you
whether your training load is ramping too fast, whether this week has been
hard-every-day, which sport actually costs you the most recovery, or *why* today is
a good or bad day to push — in numbers you can check.

This dashboard pulls your full history straight from the official WHOOP API and
answers those questions. Every call it makes shows the exact numbers and thresholds
behind it, compared with **your own** history — and every rule and threshold comes from
published research, cited below. Where a study doesn't give a number, the dashboard doesn't
invent one.

## Features

### Daily — today's call
- **Readiness** — one score (50 = your normal) from your 7-day HRV, resting HR and sleep, each
  against your previous 4 weeks, with the answer **Train hard · Go easy · Rest**.
- **Click the orb** to see every measure next to its normal range, the answer lines, and last
  night's numbers as information.
- **Warning signs** — HRV or resting HR outside your normal range, or breathing rate 3+ above
  your usual (a published illness sign).
- **Today's plan** — hard-training or easy-day advice, sleep (nights with 7+ hours), the last
  day without a workout.

### Weekly — load and injury-risk signals

<img src="docs/screenshots/weekly.png" alt="Weekly view: acute:chronic workload ratio and training variety" width="880">

- **Acute:Chronic Workload Ratio** with safe / caution / high-risk bands.
- **Training variety** (Foster monotony) — warns when a week had almost the same training
  load every day.
- Heart-rate zone time in research zones (strength sessions left out — their rest between sets
  would count as easy), sessions per week, training mix, sleep composition — all on
  Monday–Sunday weeks.

### Monthly — long-range trends

<img src="docs/screenshots/long-term.png" alt="Long-term view: recovery calendar heatmap and recovery cost by sport at the same intensity" width="880">

- **Recovery calendar heatmap** of every day on record.
- **Has readiness been right?** — every past day grouped by what readiness said, next to how you
  actually recovered the morning after, and whether the gap passes a standard significance test.
  A consistency check (recovery shares HRV and resting HR with the score), not independent proof.
- **Recovery cost by sport** — one row per sport against your other training days, with your 4
  most-played shown and the rest in a dropdown; gaps that could be chance say so.
- Trend explorer for any metric including readiness, personal records, and the full training log.

### App experience
- **Native macOS app** (Swift + WebKit) that refreshes on launch.
- **Manual refresh** button — nothing updates behind your back.
- **AI chat** with full-history context (OpenAI or Claude), conversation memory,
  and a draggable panel.
- Works on phone-width screens, respects *Reduce Motion*, no external JS libraries.

Items marked **Beyond WHOOP** in the app are metrics the WHOOP app doesn't provide.

## Try it in 30 seconds (no WHOOP needed)

Requires Python 3.9+ (preinstalled on recent macOS). No packages to install.

```bash
git clone https://github.com/jpselwan123/whoop-dashboard.git ~/whoop
cd ~/whoop
python3 scripts/generate_demo_data.py demo   # synthetic athlete, 420 days
python3 build_dashboard.py demo
open demo/index.html
```

## Setup with your WHOOP

### 1. Create a WHOOP developer app

1. Sign in at [developer.whoop.com](https://developer.whoop.com) and create an app.
2. Add a redirect URI. The default this project uses is
   `https://localhost:8080/callback` (set `WHOOP_REDIRECT_URI` in `.env` to use another).
3. Select the scopes: `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`,
   `read:profile`, `read:body_measurement`.
4. Copy the **Client ID** and **Client Secret**.

### 2. Configure

```bash
cd ~/whoop
cp .env.example .env
```

Put your Client ID and Client Secret into `.env`.

### 3. Authorize once

```bash
python3 whoop.py --auth-url
```

Open the printed link, approve access, then copy the `code=` value from the address
bar you land on (the page itself may not load — that's expected) into
`WHOOP_AUTH_CODE` in `.env`. The code is single-use and expires within minutes.

### 4. First pull

```bash
./refresh.sh          # = python3 whoop.py && python3 build_dashboard.py
open index.html
```

The first run downloads your full history. After that, a refresh token is stored in
`whoop_tokens.json`, the auth code is never needed again, and each refresh only
re-fetches the last 10 days (to catch late score corrections).

### 5. Native macOS app (optional)

```bash
./native_app/build.sh
mv "native_app/build/WHOOP Dashboard.app" /Applications/
```

The app expects the project at `~/whoop`. It isn't signed with a paid Apple
Developer ID, so the **first time**, right-click the app and choose **Open**, then
confirm. After that it opens normally.

## AI chat

Click the pulse icon (bottom right) to ask anything about your data — *"How does
soccer affect my next-day HRV?"*, *"Compare my sleep this month to last month"*,
*"Why was I flagged today?"*

| | OpenAI (default) | Anthropic |
|---|---|---|
| Model | `gpt-5.6-luna` | `claude-sonnet-5` |
| `.env` | `OPENAI_API_KEY=…` | `AI_PROVIDER=anthropic`<br>`ANTHROPIC_API_KEY=…` |
| Key from | [platform.openai.com](https://platform.openai.com/api-keys) | [console.anthropic.com](https://console.anthropic.com) |

- **Full context, compact.** Your whole history is sent as compact tables (every
  day, sleep, and workout plus the dashboard's computed numbers) — roughly 90% smaller
  than the raw WHOOP export. It stays well below the 272K-token
  point where OpenAI's long-context pricing starts.
- **Cheap.** With `gpt-5.6-luna` ($0.20 / 1M input tokens, $0.02 cached), a question
  typically costs around a cent; follow-ups reuse the cached context.
- **Conversation memory** within the open chat; the pencil icon starts a new one.
- **Key changes apply immediately** — `.env` is re-read on every question.
- Clear, plain-English errors for a missing/invalid key, no credit, rate limits,
  timeouts, and connection problems.

Set a monthly spending limit in your provider's billing settings. Model and
reasoning effort are configurable: `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`,
`ANTHROPIC_MODEL`.

## How the numbers work

Every rule and threshold below comes from a published study or consensus statement. Where the
papers leave a detail open, the dashboard follows the original method paper they cite, and
says so.

### Readiness

One number for how ready you are to train today — **50 is your normal**, every 10 points is one
standard deviation.

| Step | What the dashboard does | Source |
|---|---|---|
| Measures | ln(RMSSD) HRV, resting HR and hours asleep (naps included) — each over the **last 7 days** and for **last night** alone: 6 standard scores | HRV: [Plews et al., 2012](https://link.springer.com/article/10.1007/s00421-012-2354-4), [2014](https://www.researchgate.net/publication/259319333_Monitoring_Training_With_Heart-Rate_Variability_How_Much_Compliance_Is_Needed_for_Valid_Assessment); resting HR: [Alfonso et al., 2025](https://www.nature.com/articles/s41598-025-13540-z); sleep: [Craven et al., 2022](https://pubmed.ncbi.nlm.nih.gov/35708888/); single days for short-term response: [Schneider et al., 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6538885/), [Kiviniemi et al., 2007](https://pubmed.ncbi.nlm.nih.gov/17849143/), [Nuuttila et al., 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11541970/) |
| Your normal | The 4 weeks before the current week, updated weekly: 7-day averages compared with the spread of 7-day averages, last night compared with the spread of single nights; mean ± 0.5 SD (sample SD) is "normal" | [Vesterinen et al., 2016](https://jyx.jyu.fi/jyx/Record/jyx_123456789_50625); [Javaloyes et al., 2019](https://pubmed.ncbi.nlm.nih.gov/29809080/) — tabulated in [Manresa-Rocamora et al., 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8507742/); weekly update: [Carrasco-Poyatos et al., 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7432021/) |
| One score | All six standard scores (resting HR flipped, so lower is better) averaged with equal weights, shown on the T scale: 50 + 10 × average | Standard-score composites for athlete monitoring: [Thornton et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30676144/); equal weights when none are validated: [Dawes, 1979](https://www.researchgate.net/publication/232597503_The_robust_beauty_of_improper_linear_models_in_decision_making) |
| Answer | **55+** above normal · **45–54** normal → **Train hard**; **35–44** below normal → **Go easy**; **under 35** → **Rest** | ±0.5 SD decision line: Javaloyes 2019, [Kiviniemi et al., 2007](https://pubmed.ncbi.nlm.nih.gov/17849143/); 1.5 SD below "worth acting on": Thornton 2019 |
| Illness sign | Breathing rate last night 3+ breaths/min above your usual (average of nights 30–90 days before, 30+ nights) → **Rest** | [Natarajan et al., 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8443549/) |
| Hard days in a row | After 2 moderate/high-intensity days in a row → **Go easy** | Carrasco-Poyatos 2020 |
| Session today | After a moderate or high-intensity session, the rest of the day is for recovery | [Stanley, Peake & Buchheit, 2013](https://link.springer.com/article/10.1007/s40279-013-0083-4) |

Last night counts for half the score and the last 7 days for the other half, so a strong night lifts
readiness without a single night deciding it (single nights are noisy: Plews 2012). The raw values and
WHOOP recovery are shown next to the score.

### Other metrics

| Metric | Definition | Source |
|---|---|---|
| **Intensity zones** | Easy below ~82% of max HR, moderate 82–87%, hard above 87%. WHOOP's zones are % of heart-rate *reserve*, so each is converted with your resting and max HR and its minutes split across the lines in proportion. A session's intensity is where most of its time was. | [Seiler & Kjerland, 2006](https://pubmed.ncbi.nlm.nih.gov/16430681/); Seiler 2010; [WHOOP zones use heart-rate reserve](https://www.whoop.com/us/en/thelocker/why-whoop-uses-heart-rate-reserve-not-max-heart-rate/) |
| **Training variety** | Foster's monotony = a week's mean daily training load ÷ its SD, 0 on days without training, complete weeks only; above 2.0 flagged. Training load = Edwards' TRIMP (minutes at 50–60 / 60–70 / 70–80 / 80–90 / 90–100% of max HR × 1–5), because WHOOP doesn't record Foster's session RPE and strain (a logarithmic 0–21 scale) can't be added across sessions. The chart shows your WHOOP day strain. | [Foster et al., 2001](https://www.researchgate.net/publication/11645805_A_New_Approach_to_Monitoring_Exercise_Training); Edwards 1993 |
| **Load ratio (ACWR)** | Average strain over the last 7 calendar days ÷ last 28 (21+ days of data); bands 0.8 / 1.3 / 1.5 | Gabbett 2016 — predictive value disputed by [Impellizzeri et al., 2020](https://www.researchgate.net/publication/341936245_AcuteChronic_Workload_Ratio_Conceptual_Issues_and_Fundamental_Pitfalls) |
| **Sleep** | Nights in the last 7 with 7+ hours asleep | [AASM & Sleep Research Society, Watson et al., 2015](http://jcsm.aasm.org/doi/10.5664/jcsm.4758) |
| **Rest day** | The last finished day with no logged workout — a fact, no threshold | — |
| **Sport recovery cost** | One row per sport: next-morning recovery after days that sport was your hardest session, vs all your other training days, with the intensity most of those days were. Your 4 most-played sports are shown, the rest in a dropdown; a gap counts as real only with 30+ days on both sides and Welch's t-test p < 0.05, otherwise the number is prefixed with ~ | Standard statistical conventions |
| **Has readiness been right?** | Next-morning recovery after Train hard, Go easy and Rest days; Train hard vs the rest tested the same way | Standard statistical conventions |
| **▲▼ vs 30-day average** | Shown after 28 days; "= avg" when within ±0.5 SD of the last 30 days | Same smallest-worthwhile-change line as the protocol |

**Honest limits.** The protocol comes from endurance-athlete trials that measured HRV on waking;
WHOOP measures it during sleep (overnight values track training at least as well —
[Nuuttila et al., 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11541970/)). Equal weights and the
T scale are standard ways to combine measures, not weights validated for this purpose. Zone
conversion assumes minutes are evenly spread inside each WHOOP zone. Self-reported well-being, which
the trials also used, isn't available from the WHOOP API.

## Architecture

```mermaid
flowchart LR
    W[(WHOOP API v2)] -- OAuth 2.0 --> P[whoop.py<br/>incremental sync]
    P --> R[whoop_data.json]
    R --> B[build_dashboard.py<br/>metrics]
    B --> D[dashboard_data.json]
    B --> H[index.html]
    H <--> S[chat_server.py<br/>127.0.0.1 only]
    S -- refresh --> P
    S --> C[ai_context.py<br/>compact tables]
    C --> S
    S -- question + context --> AI[(OpenAI / Anthropic)]
    A[macOS app<br/>Swift + WebKit] --> H
    A -. starts .-> S
```

```
whoop-dashboard/
├── whoop.py                  # WHOOP OAuth + incremental data sync
├── build_dashboard.py        # all metrics; renders index.html from the template
├── dashboard_template.html   # the dashboard UI (vanilla JS + hand-built SVG charts)
├── chat_server.py            # local server: AI chat, refresh, data endpoint
├── ai_context.py             # full history → compact tables for the AI model
├── env_config.py             # .env loader + atomic file writes
├── refresh.sh                # pull + build in one step
├── CLAUDE.md                 # conventions for AI coding agents
├── native_app/               # macOS app (main.swift, build.sh, icon)
├── scripts/
│   ├── generate_demo_data.py # synthetic WHOOP export for demo + tests
│   └── privacy_scan.py       # blocks commits containing personal data
├── tests/                    # unit tests (no network, no secrets)
└── docs/screenshots/
```

**Design choices**
- **Zero dependencies** — Python standard library and plain browser APIs only.
  Nothing to install, nothing to go out of date.
- **Crash-safe writes** — every data file is written to a temp file and atomically
  renamed, so a force-quit can't corrupt your history or OAuth tokens.
- **Fail-safe UI** — animations never gate visibility; an empty or brand-new account
  shows clear "not enough data yet" states instead of broken charts.

## Privacy & security

- **Local-first.** Your data is stored only on your Mac. The only network calls go to
  WHOOP (to fetch your data) and — only when you ask the chat something — to the AI
  provider you configured.
- **Secrets never leave the backend.** API keys are read by the local server and never
  reach the web page. The server listens on `127.0.0.1` only.
- **What the chat sends:** your history as tables plus the conversation. It does
  **not** include your email, last name, WHOOP user ID, or record IDs. OpenAI requests
  are sent with `store: false`. Conversations are kept only in the open window.
- **Nothing personal is committed.** `.env`, `whoop_tokens.json`, and all generated
  data files are git-ignored. Tests and screenshots use synthetic data only.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Development

```bash
python3 -m unittest discover -s tests -t tests -v
```

The test suite runs on synthetic data against a fake AI provider — no network, no
API keys, no cost. It covers metric calculations and edge cases (no workouts, missing
vitals, brand-new accounts), the privacy of the AI context, and the chat backend's
request format, conversation handling, input validation, and error messages.
GitHub Actions runs it on Python 3.9 and 3.12 and compiles the macOS app on every
push.

Before publishing changes, run the privacy scan — it fails if any tracked file contains
a value from your `.env`, your WHOOP tokens, identifiers from your own WHOOP export, or a
home-directory path:

```bash
python3 scripts/privacy_scan.py
```

`CLAUDE.md` documents the codebase conventions for AI coding agents.

## Limitations

- The native app is macOS-only; the dashboard itself works in any modern browser.
- The app isn't notarized (that needs a paid Apple Developer account), hence the
  one-time right-click → Open.
- The local server uses port `8934`; if something else uses it, change `PORT` in
  `chat_server.py` and the matching URLs in `dashboard_template.html`.
- Sport comparisons and the "Does this work?" check are correlations, not controlled experiments.
- Intensity zones depend on the max heart rate stored in your WHOOP profile; if it's wrong, zones shift.

## License & disclaimer

[MIT](LICENSE).

This is an independent personal project. It is **not affiliated with, endorsed by,
or supported by WHOOP, Inc.** "WHOOP" is a trademark of WHOOP, Inc., used here only
to describe compatibility with its public API.

This software is for fitness self-tracking and **is not medical advice**. It does not
diagnose, treat, or prevent any condition. Talk to a qualified professional about
health concerns.
