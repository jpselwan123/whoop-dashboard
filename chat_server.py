"""Local-only backend that runs alongside the dashboard while the app is open.

Two jobs, both on-demand only — nothing here runs on a timer or touches the
network unless the person using the dashboard asks it to:
1. Chat backend for the "Ask" popup — holds the AI provider's API key server-side
   (never sent to the browser), builds the full-history data context fresh per
   question (see ai_context.py), and forwards the conversation to the model.
   Works with OpenAI (default: gpt-5.6-luna) or Anthropic, chosen in .env.
2. Manual data refresh — POST /refresh re-runs the same WHOOP fetch + rebuild
   that refresh.sh does on launch, triggered by the refresh button on the page.

Binds to 127.0.0.1 only — never reachable from outside this machine.

Run standalone with `python3 chat_server.py`, or let the native app spawn it.
"""
import json, os, subprocess, threading, urllib.error, urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from env_config import load_env
from ai_context import build_context_text

load_env()

HOST = "127.0.0.1"
PORT = 8934
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env")
DATA_FILE = os.path.join(HERE, "dashboard_data.json")
refresh_lock = threading.Lock()

DEFAULT_MODELS = {"openai": "gpt-5.6-luna", "anthropic": "claude-sonnet-5"}
REQUEST_TIMEOUT = 90          # seconds to wait on the AI provider
MAX_OUTPUT_TOKENS = 4000      # includes the model's internal reasoning tokens
MAX_TURNS = 40                # messages kept from one conversation
MAX_MESSAGE_CHARS = 8000      # per message
MAX_HISTORY_CHARS = 60000     # whole conversation, oldest turns dropped first

SYSTEM_PROMPT = """You are the assistant inside a personal WHOOP dashboard. The person \
asking is the owner of the data below — their complete WHOOP history (every day, sleep, \
and workout) plus the exact numbers their dashboard computed.

How to answer:
- Ground everything in their data. Quote real numbers, dates, and ranges from the tables; \
compute from the rows when needed (averages, comparisons, trends, correlations) and say what \
period you used.
- If the data can't answer something, say so plainly. Never invent a number.
- Never explain a number by guessing at a bug, a refresh lag, a time-zone slip or a "date mismatch". \
The tables and the dashboard summaries are the same data, pulled at the time given as "Data last \
pulled from WHOOP". If something looks contradictory, re-read the rows and explain what the figure \
actually means; if it still does not reconcile, say exactly which two numbers disagree and stop there.
- Keep it short: a sentence or two for simple questions, a short paragraph or a few short \
lines for bigger ones. Plain text; **bold** is fine for key numbers. No headers, no tables.
- General training, sleep, and recovery questions are welcome — tie the answer back to their \
numbers where it helps.
- Relationships in this data are correlations, not proof of cause — say so when it matters.
- Not medical advice: for pain, illness, or worrying symptoms, suggest seeing a professional.
- Write every duration the way the WHOOP app does: hours and minutes ("2h 26m", "6h 04m"), never \
decimal hours. The sleep tables are already h:mm; convert any decimal-hour field (e.g. \
sleep_debt_hours 2.13 → 2h 08m) before quoting it.
- Sleep has two percentages: "sleep performance" = WHOOP's Sleep Performance (perf; since WHOOP's \
2025 update a blend of hours vs needed, consistency, efficiency and sleep stress) and "hours vs \
needed" (vs_needed = time asleep ÷ sleep need). Name which one you quote.

Dashboard terms they may ask about (every rule below is taken from published research):
- Readiness (dashboard_summaries.readiness.score, 0–100, a percentile of their own days — 50 = a \
median day for them, NOT a percentage of anything): averages of ln(RMSSD) HRV, resting HR and hours \
asleep over the 7 days BEFORE today (the window stops the day before, so last night is counted once, \
not twice) and last night on its own - six inputs, so last night is half the score - each a standard \
score against the 7-day averages \
of the 4 weeks before the current week (sample SD; normal = ±0.5 SD, shown as .normal ranges), resting \
HR flipped, averaged with equal weights (Thornton 2019), then standardised against the spread of their \
own earlier scores and read off the normal curve as a percentile (averaging standard scores shrinks \
their spread, so the average is not on a 1-SD scale of its own). It prescribes one session for \
the day, the way the HRV-guided trials did: 31+ Train as planned (the trials' moderate/high session; \
no cited trial prescribes a harder session for being above the band, so there is no answer above it), \
and below the band Go easy or Rest: rest when the fall is large (under 7, \
1.5 SD below) or sustained - the 3rd day in a row below the band - and never more than 2 rest days in \
a row (Manresa-Rocamora 2021 "low intensity exercise (or passive rest)"; Plews 2013 and Buchheit 2014 \
on reading sustained rather than single-day changes; Kiviniemi 2007 on consecutive rest days). Rest if breathing rate last night is 3+ \
above the usual (nights 30–90 days back; Natarajan 2021); Go easy after 2 hard days in a row \
(Carrasco-Poyatos 2020). Once they have trained today the page shows "Done for today" — the day's plan \
is spent — and says whether what they did matched the plan; recovery from a session takes about 24h \
(low/moderate) to 48h (high intensity) (Stanley 2013). readiness.reasons lists why; last_night is \
information only.
- Intensity: Seiler's three zones — easy below ~82% of max HR, moderate 82–87%, hard above 87% — \
converted from WHOOP's heart-rate-reserve zones with the person's resting and max HR. A session's \
intensity is where most of its time was; strength sessions have none.
- Training variety: Foster's monotony = weekly mean ÷ SD of daily training load (Edwards TRIMP from \
heart-rate zone minutes, 0 on days off), complete weeks only; above 2.0 is the risk line. WHOOP strain is \
logarithmic and must never be added across sessions.
- Load ratio (ACWR): last-7-days average strain ÷ last-28-days average; bands 0.8 / 1.3 / 1.5 are \
widely used but disputed. The newest value includes today's strain so far, so it rises through the \
day. dashboard_summaries.load_today gives today's ratio and strain_at = the day strain at which it \
would cross each band (algebra on the band, not a new threshold). Before any session today the page \
steps the plan down as it climbs: past 1.5 the plan becomes Go easy. After a session it is reported, not used to rewrite the plan.
- After a session the orb shows readiness after training (dashboard_summaries.training_cost): this \
morning's score minus what today's strain costs by tomorrow morning, measured on their own history \
(per_strain = readiness points per point of day strain, holding readiness constant; applied to strain \
above a typical rest day; only if significant). Readiness itself is an overnight measurement.
- "Today" is the current WHOOP day (from one sleep to the next, today_snapshot with in_progress), \
not the calendar date - at 1am before sleeping they are still in the same WHOOP day.
- Rest day ("last day off" on the page): the most recent finished day with NO workout logged. It is \
not the last day they trained - their most recent workout is the newest row of the workouts table. \
Read the card as "the last day they did nothing", never as "the last day they did something".
- Sleep: nights with 7+ hours asleep in the last 7 (AASM/SRS adult recommendation).
- Recovery cost by sport (dashboard_summaries.sport_recovery_cost.sports): one row per sport — \
next-morning recovery after days that sport was the hardest session, vs all other training days, with \
the intensity most of those days were. significant = 30+ days on both sides and Welch p < 0.05; \
otherwise the page prefixes the number with ~.
- "Does following the plan pay off?" (plan_check): next-morning recovery after days they followed the \
plan vs days they did a moderate/high-intensity session on a Go easy or Rest day. Welch, p < 0.05, 30+ \
per group, otherwise the counts only. If it comes up, say the p-value is optimistic because consecutive \
days are not independent. Comparing the score against WHOOP recovery was dropped: recovery is built \
from the same HRV and resting HR, so the two agree by construction.
- Heart-rate zone split excludes strength sessions."""


def env_value(key):
    """Read a setting fresh from .env on every request, so adding or changing an API key
    takes effect immediately — no need to restart the app. Real environment variables
    still win (useful for running this outside the app)."""
    if os.environ.get(key, "").strip() and key not in _loaded_from_file:
        return os.environ[key].strip()
    try:
        for line in open(ENV_FILE):
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# keys load_env() copied in from .env at startup — those are re-read from the file instead
_loaded_from_file = set()
try:
    for _line in open(ENV_FILE):
        if "=" in _line and not _line.strip().startswith("#"):
            _loaded_from_file.add(_line.partition("=")[0].strip())
except OSError:
    pass


def pick_provider():
    """Returns (provider, api_key, model) or raises ValueError with a readable message."""
    choice = env_value("AI_PROVIDER").lower()
    openai_key, anthropic_key = env_value("OPENAI_API_KEY"), env_value("ANTHROPIC_API_KEY")
    if choice not in ("", "openai", "anthropic"):
        raise ValueError(f'AI_PROVIDER in .env is "{choice}" — use "openai" or "anthropic".')
    if not choice:
        choice = "openai" if openai_key or not anthropic_key else "anthropic"
    key = openai_key if choice == "openai" else anthropic_key
    if not key:
        name = "OPENAI_API_KEY" if choice == "openai" else "ANTHROPIC_API_KEY"
        raise ValueError(f"No API key yet — add {name}=... to the .env file in the whoop folder, then ask again.")
    model = env_value("OPENAI_MODEL" if choice == "openai" else "ANTHROPIC_MODEL") or DEFAULT_MODELS[choice]
    return choice, key, model


def clean_messages(payload):
    """Accepts {"messages":[{role,content},...]} (a conversation) or the older
    {"question": "..."} shape. Returns a validated, size-capped list ending on a user turn."""
    if isinstance(payload.get("messages"), list):
        msgs = payload["messages"]
    elif isinstance(payload.get("question"), str):
        msgs = [{"role": "user", "content": payload["question"]}]
    else:
        raise ValueError('expected JSON body: {"messages": [{"role": "user", "content": "..."}]}')

    out = []
    for m in msgs[-MAX_TURNS:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            raise ValueError("each message needs a role of user/assistant and text content")
        text = m["content"].strip()[:MAX_MESSAGE_CHARS]
        if text:
            out.append({"role": m["role"], "content": text})
    if not out or out[-1]["role"] != "user":
        raise ValueError("empty question")

    while sum(len(m["content"]) for m in out) > MAX_HISTORY_CHARS and len(out) > 1:
        out.pop(0)
    while out and out[0]["role"] != "user":   # both providers expect the first turn to be the user's
        out.pop(0)
    return out


def with_today(messages):
    """Stamp the current local time onto the newest question only — the model has no
    clock, and keeping earlier turns untouched keeps the cached prompt prefix stable."""
    stamp = datetime.now().astimezone().strftime("%a %d %b %Y, %H:%M (UTC%z)")
    last = dict(messages[-1], content=f"[Now: {stamp}]\n{messages[-1]['content']}")
    return messages[:-1] + [last]


def http_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.load(resp)


def ask_openai(messages, api_key, model, context):
    body = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        # data first, conversation after: the long identical prefix is what OpenAI caches
        "input": [{"role": "developer", "content": context}] + with_today(messages),
        "reasoning": {"effort": env_value("OPENAI_REASONING_EFFORT") or "low"},
        "text": {"verbosity": "low"},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "prompt_cache_key": "whoop-dashboard",
        "store": False,   # don't keep these conversations on OpenAI's side
    }
    result = http_json(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/responses",
                       body, {"authorization": f"Bearer {api_key}"})
    text = "".join(part.get("text", "")
                   for item in result.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    if not text.strip():
        reason = (result.get("incomplete_details") or {}).get("reason")
        if reason == "max_output_tokens":
            raise RuntimeError("The model ran out of room before answering — try a narrower question.")
        raise RuntimeError("The model returned an empty answer — try asking again.")
    usage = result.get("usage") or {}
    return text, {"input": usage.get("input_tokens"), "output": usage.get("output_tokens"),
                  "cached": (usage.get("input_tokens_details") or {}).get("cached_tokens")}


def ask_anthropic(messages, api_key, model, context):
    body = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT},
                   {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}}],
        "messages": with_today(messages),
    }
    result = http_json(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") + "/messages",
                       body, {"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    text = "".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise RuntimeError("The model returned an empty answer — try asking again.")
    usage = result.get("usage") or {}
    return text, {"input": usage.get("input_tokens"), "output": usage.get("output_tokens"),
                  "cached": usage.get("cache_read_input_tokens")}


def friendly_http_error(provider, e):
    """Turn a provider HTTP error into one plain sentence (no raw JSON in the chat)."""
    name = "OpenAI" if provider == "openai" else "Anthropic"
    try:
        err = json.loads(e.read().decode(errors="replace")).get("error") or {}
    except Exception:
        err = {}
    code, message = (err.get("code") or err.get("type") or ""), (err.get("message") or "")
    if e.code == 401:
        return f"{name} didn't accept the API key — check it in .env (no spaces or quotes around it)."
    if e.code == 403:
        return f"This {name} key doesn't have access to that model or project. {message}".strip()
    if e.code == 404:
        return f"{name} doesn't recognize the model name — check the model setting in .env. {message}".strip()
    if e.code == 429 and code in ("insufficient_quota", "billing_hard_limit_reached"):
        return f"Your {name} account is out of credit or hit its spending limit — top up in billing settings."
    if e.code == 429:
        return f"{name} is rate-limiting requests — wait a few seconds and try again."
    if e.code in (400, 413) and ("context" in message.lower() or "too long" in message.lower()):
        return "This conversation got too long for the model — close and reopen the chat to start fresh."
    if e.code >= 500:
        return f"{name} is having problems right now ({e.code}) — try again in a minute."
    return f"{name} error ({e.code}): {message[:200] or 'request rejected'}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout quiet; nothing here is sensitive but it's also not useful

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Serves dashboard_data.json over HTTP rather than the page fetching the
        # file:// path directly — WKWebView/Safari blocks fetch() to local files
        # even from a file:// page in many cases, so this is the reliable path.
        if self.path.split("?")[0] != "/data":
            return self._json(404, {"error": "not found"})
        try:
            with open(DATA_FILE, "rb") as f:
                body = f.read()
        except Exception as e:
            return self._json(500, {"error": f"Couldn't read dashboard_data.json: {e}"})
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/refresh":
            return self._handle_refresh()
        if self.path != "/ask":
            return self._json(404, {"error": "not found"})

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 1_000_000:
                return self._json(413, {"error": "That message is too large."})
            messages = clean_messages(json.loads(self.rfile.read(length) or b"{}"))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            return self._json(400, {"error": 'expected JSON body: {"messages": [...]}'})

        try:
            provider, api_key, model = pick_provider()
        except ValueError as e:
            return self._json(400, {"error": str(e)})

        try:
            context = build_context_text()
        except FileNotFoundError:
            return self._json(500, {"error": "No WHOOP data on disk yet — click refresh first."})
        except Exception as e:
            return self._json(500, {"error": f"Couldn't read your WHOOP data: {e}"})

        ask = ask_openai if provider == "openai" else ask_anthropic
        try:
            answer, usage = ask(messages, api_key, model, context)
        except urllib.error.HTTPError as e:
            return self._json(502, {"error": friendly_http_error(provider, e)})
        except (TimeoutError, OSError) as e:
            if "timed out" in str(e).lower():
                return self._json(504, {"error": "The AI took too long to answer — try again."})
            return self._json(502, {"error": "Couldn't reach the AI service — check your internet connection."})
        except RuntimeError as e:
            return self._json(502, {"error": str(e)})
        except Exception as e:
            return self._json(502, {"error": f"Unexpected response from the AI service: {e}"})

        self._json(200, {"answer": answer, "model": model, "usage": usage})

    def _handle_refresh(self):
        if not refresh_lock.acquire(blocking=False):
            return self._json(409, {"error": "A refresh is already in progress — wait for it to finish."})
        try:
            subprocess.run(["python3", "whoop.py"], cwd=HERE, check=True, timeout=60,
                            capture_output=True, text=True)
            subprocess.run(["python3", "build_dashboard.py"], cwd=HERE, check=True, timeout=60,
                            capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or "").strip().splitlines()
            return self._json(502, {"error": f"Refresh failed: {detail[-1] if detail else e}"})
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": "Refresh timed out — WHOOP's API may be slow or unreachable right now."})
        except Exception as e:
            return self._json(502, {"error": f"Refresh failed: {e}"})
        finally:
            refresh_lock.release()
        self._json(200, {"ok": True})


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        raise SystemExit(
            f"Couldn't start the local server on port {PORT}: {e}\n"
            f"Something else on this Mac is already using port {PORT}. Either quit "
            f"that process, or change PORT in chat_server.py — and update the matching "
            f"CHAT_URL/REFRESH_URL/DATA_URL constants in dashboard_template.html to match."
        )
    print(f"Chat server listening on http://{HOST}:{PORT} (local only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
