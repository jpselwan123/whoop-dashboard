"""Pull your WHOOP history into whoop_data.json via the official WHOOP API (v2).

First run needs a one-time authorization code:
    python3 whoop.py --auth-url     # prints the WHOOP login link to open
After that, a refresh token is stored in whoop_tokens.json and every later run
only fetches the last few days and merges them in.
"""
import json, os, secrets, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from env_config import load_env, atomic_write_json

load_env()

CLIENT_ID     = os.environ.get("WHOOP_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "").strip()
AUTH_CODE     = os.environ.get("WHOOP_AUTH_CODE", "").strip()   # only needed the first time, before whoop_tokens.json exists
if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit("WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET must be set in .env — see README.md (Setup).")

# must exactly match a redirect URI registered on your app at developer.whoop.com
REDIRECT = os.environ.get("WHOOP_REDIRECT_URI", "").strip() or "https://localhost:8080/callback"
SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
BASE = "https://api.prod.whoop.com/developer"
STORE = "whoop_tokens.json"
DATA_FILE = "whoop_data.json"
LOOKBACK_DAYS = 10  # re-fetch this trailing window each run to catch late-finalized/corrected scores

def post(data):
    req = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "whoop-dashboard/1.0"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(
            f"WHOOP rejected the token request ({e.code}): {detail}\n"
            f"Double check WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, and WHOOP_AUTH_CODE in .env — "
            f"the auth code is single-use and only valid for a few minutes after you generate it."
        )

def tokens():
    if not os.path.exists(STORE) and not AUTH_CODE:
        raise SystemExit(
            "No whoop_tokens.json yet and WHOOP_AUTH_CODE isn't set in .env — the very first run "
            "needs a fresh authorization code from WHOOP. See README.md."
        )
    if os.path.exists(STORE):
        t = json.load(open(STORE))
        if t["expires_at"] > time.time() + 120:
            return t
        t = post({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                  "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": "offline"})
    else:
        t = post({"grant_type": "authorization_code", "code": AUTH_CODE,
                  "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "redirect_uri": REDIRECT})
    t["expires_at"] = time.time() + t["expires_in"]
    # write BEFORE using: each refresh kills the old pair, so a lost write locks you out
    atomic_write_json(STORE, t)
    return t

def get(path, at):
    req = urllib.request.Request(BASE + path,
        headers={"Authorization": "Bearer " + at, "User-Agent": "whoop-dashboard/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))

def page(path, at, start=None, cap=100000):
    out, tok = [], None
    while True:
        params = {"limit": 25}
        if start:
            params["start"] = start
        if tok:
            params["nextToken"] = tok
        url = f"{path}?{urllib.parse.urlencode(params)}"
        d = get(url, at)
        out += d.get("records", [])
        tok = d.get("next_token")
        if not tok or len(out) >= cap:
            return out
        time.sleep(0.15)

def merge(existing, fresh, key):
    by_key = {item[key]: item for item in existing}
    for item in fresh:
        by_key[item[key]] = item
    return list(by_key.values())

if "--auth-url" in sys.argv:
    print("1. Open this link, log in to WHOOP, and approve access:\n")
    print(AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPES, "state": secrets.token_hex(8)}))
    print("\n2. Your browser is sent to your redirect URL (the page itself may fail to load — that's fine).")
    print("   Copy the value after `code=` in the address bar into WHOOP_AUTH_CODE in .env.")
    print("3. Run `python3 whoop.py` within a few minutes — the code is single-use and short-lived.")
    sys.exit(0)

at = tokens()["access_token"]

existing = json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else None
incremental = existing is not None
start = None
if incremental:
    start = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

fresh = {
    "profile":  get("/v2/user/profile/basic", at),
    "body":     get("/v2/user/measurement/body", at),
    "recovery": page("/v2/recovery", at, start=start),
    "cycles":   page("/v2/cycle", at, start=start),
    "sleep":    page("/v2/activity/sleep", at, start=start),
    "workouts": page("/v2/activity/workout", at, start=start),
}

if incremental:
    data = {
        "profile": fresh["profile"],
        "body": fresh["body"],
        "recovery": merge(existing["recovery"], fresh["recovery"], "cycle_id"),
        "cycles": merge(existing["cycles"], fresh["cycles"], "id"),
        "sleep": merge(existing["sleep"], fresh["sleep"], "id"),
        "workouts": merge(existing["workouts"], fresh["workouts"], "id"),
    }
else:
    data = fresh

atomic_write_json(DATA_FILE, data, indent=2)
print({k: (len(v) if isinstance(v, list) else 1) for k, v in data.items()},
      "(incremental, last %dd)" % LOOKBACK_DAYS if incremental else "(full history)")
