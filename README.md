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

<img src="docs/screenshots/overview.png" alt="Daily view: training call, readiness orb, recovery, strain, sleep" width="880">

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
behind it, calibrated to **your own** history rather than generic cut-offs.

## Features

### Daily — today's call
- **One clear decision** (Green light · Moderate · Ease off · Done for today) with a
  short reason, driven by a single priority chain so the badge, pill, and headline
  can never contradict each other.
- **Day badge** (Red flag · Recovery · Peak · Grind). Click it to see today's numbers
  next to the line where each one flags, and how every badge is decided.
- **Readiness score** blending recovery, sleep performance, recent load, and sleep
  debt, with a scale showing where today sits between *your* rest and push thresholds.
- **Vitals at a glance** — recovery, HRV, resting HR, sleep, sleep debt, and 7-day
  strain, each with its change vs your 30-day average (green = better, red = worse).
- **Today's plan** — which kind of session fits today, based on how *you* have
  recovered from each sport before.
- **Fatigue signal** — flags nights when HRV, resting heart rate, or breathing rate
  leave your personal normal range.

### Weekly — load and injury-risk signals

<img src="docs/screenshots/weekly.png" alt="Weekly view: acute:chronic workload ratio and training variety" width="880">

- **Acute:Chronic Workload Ratio** with safe / caution / high-risk bands.
- **Training variety** (Foster monotony) — warns when a week has been unusually
  hard-every-day *for you*.
- Heart-rate zone time, sessions per week, training mix, sleep composition,
  day-of-week patterns — all on Monday–Sunday weeks.

### Monthly — long-range trends

<img src="docs/screenshots/long-term.png" alt="Long-term view: recovery calendar heatmap, monthly averages, next-morning recovery per sport" width="880">

- **Recovery calendar heatmap** of every day on record.
- **Monthly averages** that show real gaps and fade partial months instead of
  hiding them.
- **Next-morning recovery after each sport** — what each sport typically costs you.
- Trend explorer for any metric, personal records, and the full training log.

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

Everything is computed from your own history. Thresholds adapt to you.

| Metric | Definition | Flags at |
|---|---|---|
| **Readiness** | Weighted blend: recovery 45%, sleep performance 25%, 7-day vs 30-day strain 20%, sleep debt 10% | Peak ≥ your 70th-percentile recovery · Recovery < your 25th percentile |
| **Load ratio (ACWR)** | Last-7-day average strain ÷ last-28-day average | Safe 0.8–1.3 · Caution 1.3–1.5 · High > 1.5 |
| **Training variety** | Foster monotony (weekly mean ÷ SD of daily strain) × weekly load | This week above 80% of your last 16 weeks |
| **Fatigue signal** | Each night's HRV, resting HR, and breathing rate vs your previous 30 nights | Outside ±1.5 standard deviations (shown in the app as plain limits, e.g. "flags at 16.4+ /min") |
| **Rest day** | A day in your bottom 15% of strain | 7+ days without one |
| **Sport recovery cost** | Average next-morning recovery after days whose hardest session was that sport, vs your overall average | Sports with 8+ sessions |

**Day badge — checked in order, first match wins**

1. **Red flag** — a fatigue signal in the last 14 days, *or* all three of: 7+ days
   since rest, a week harder than 80% of recent weeks, and ACWR above 1.3.
2. **Recovery** — readiness below your rest threshold, *or* today's strain already
   above your 7-day average.
3. **Peak** — readiness at or above your push threshold.
4. **Grind** — everything in between.

Readiness and the daily call are a model built on top of WHOOP's scores; every other
number is WHOOP data or a direct calculation from it.

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
- Sport and weekday comparisons are correlations, not controlled experiments.

## License & disclaimer

[MIT](LICENSE).

This is an independent personal project. It is **not affiliated with, endorsed by,
or supported by WHOOP, Inc.** "WHOOP" is a trademark of WHOOP, Inc., used here only
to describe compatibility with its public API.

This software is for fitness self-tracking and **is not medical advice**. It does not
diagnose, treat, or prevent any condition. Talk to a qualified professional about
health concerns.
