"""Small shared helpers: a minimal .env loader (avoids adding python-dotenv as a
dependency) and an atomic file-write helper used everywhere this project writes
JSON or HTML to disk.
"""
import json, os

def load_env(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def atomic_write(path, text):
    """Write text to path without ever leaving a truncated/corrupt file behind if
    the process is killed mid-write (a force-quit, or a subprocess timeout) — write
    to a temp file first, then rename, which is atomic on the filesystem."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def atomic_write_json(path, data, indent=None):
    atomic_write(path, json.dumps(data, indent=indent))
