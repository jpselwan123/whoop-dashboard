"""Pre-publish privacy scan: fails if anything personal is about to be committed.

Checks every tracked file (or staged files with --staged) for:
- any secret value from .env (API keys, WHOOP client secret, auth code)
- WHOOP OAuth tokens from whoop_tokens.json, and the local-server token from .dashboard_token
- identifiers from your own WHOOP export (email, last name, user id)
- absolute home-directory paths and common key/token formats

Nothing personal is hardcoded here — identifiers are read at runtime from your
local, git-ignored files, so the scan is safe to keep in a public repo.

Usage: python3 scripts/privacy_scan.py [--staged]      exit 0 = clean, 1 = issues
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PATTERNS = {
    "home directory path": r"/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/",
    "OpenAI key": r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}
ALLOWED_FILES = {"scripts/privacy_scan.py"}  # contains the patterns themselves


def local_secrets():
    found = []
    if os.path.exists(".env"):
        for line in open(".env"):
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if len(value) >= 16 and "MODEL" not in key:
                found.append((f".env {key.strip()}", value))
    if os.path.exists("whoop_tokens.json"):
        tokens = json.load(open("whoop_tokens.json"))
        for key in ("access_token", "refresh_token"):
            if tokens.get(key):
                found.append((f"WHOOP {key}", tokens[key]))
    if os.path.exists(".dashboard_token"):
        value = open(".dashboard_token").read().strip()
        if value:
            found.append(("local-server token", value))
    if os.path.exists("whoop_data.json"):
        profile = json.load(open("whoop_data.json")).get("profile", {})
        for key in ("email", "last_name"):
            if profile.get(key):
                found.append((f"WHOOP profile {key}", str(profile[key])))
        if profile.get("user_id"):
            found.append(("WHOOP user_id", str(profile["user_id"])))
    return found


def files_to_scan(staged):
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    return [f for f in subprocess.check_output(cmd).decode().splitlines() if f and os.path.isfile(f)]


def main():
    staged = "--staged" in sys.argv
    secrets = local_secrets()
    issues = 0
    files = files_to_scan(staged)
    for path in files:
        if path in ALLOWED_FILES:
            continue
        text = open(path, "rb").read().decode("latin-1")
        for label, value in secrets:
            if value in text:
                print(f"  ✗ {path}: contains {label}")
                issues += 1
        for label, pattern in PATTERNS.items():
            for m in re.finditer(pattern, text):
                print(f"  ✗ {path}: {label} → {m.group(0)[:12]}…")
                issues += 1
    for ignored in (".env", "whoop_tokens.json", "whoop_data.json", "dashboard_data.json", "index.html",
                    ".dashboard_token"):
        if subprocess.run(["git", "ls-files", "--error-unmatch", ignored], capture_output=True).returncode == 0:
            print(f"  ✗ {ignored} is tracked by git — it must never be committed")
            issues += 1
    print(f"privacy scan: {len(files)} files, {issues} issue(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
