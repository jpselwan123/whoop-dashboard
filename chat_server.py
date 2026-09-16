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
- Keep it short: a sentence or two for simple questions, a short paragraph or a few short \
lines for bigger ones. Plain text; **bold** is fine for key numbers. No headers, no tables.
- General training, sleep, and recovery questions are welcome — tie the answer back to their \
numbers where it helps.
- Relationships in this data are correlations, not proof of cause — say so when it matters.
- Not medical advice: for pain, illness, or worrying symptoms, suggest seeing a professional.

Dashboard terms they may ask about:
- Readiness (differs from recovery): 7-day rolling ln(RMSSD) HRV and resting HR plus 3-night \
sleep performance, each vs the person's previous 60 days (normal = mean ± 0.5 SD), equal \
weights, score = 50 + 25 × average (50 = normal). 63+ above normal, 38–62 normal, under 38 below \
normal. Readiness describes the body; the daily answer is the single call and can override it. \
Inputs and normal ranges are in dashboard_summaries.readiness.
- Daily answer, first match wins: Rest (HRV, resting HR, or breathing rate outside their normal \
range in the last 14 days — normal = their last 30 nights — OR all three of: 7+ days since a \
rest day, this week harder than 80%+ of recent weeks, and last-7-days vs last-28-days load \
above 1.3×) → Go easy (readiness below normal, or today's strain already above the 7-day \
average) → Push (readiness above normal) → Train (readiness normal).
- Load ratio (ACWR): last-7-days average strain ÷ last-28-days average. 0.8–1.3 is the usual \
safe band; above 1.3 caution; above 1.5 high.
- Rest day: a day with strain in their own bottom 15%.
- Next-morning recovery after each sport: average recovery the morning after days whose \
hardest session was that sport, compared with their overall average."""


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
