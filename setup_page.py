"""The page a new user sees before there is anything to show: a setup checklist.

build_dashboard.py writes it as index.html only when there is no data yet (no whoop_data.json, or no
scored night in it), so it can never replace a working dashboard. Each step is ticked from what is on
disk; the first unticked one is marked as next. The page carries no data, no secrets and no paths:
only whether each file or setting exists.
"""
import os

STEPS = [
    ('Create a WHOOP developer app',
     'Sign in at <a href="https://developer.whoop.com">developer.whoop.com</a>, create an app with the redirect URI '
     '<code>https://localhost:8080/callback</code>, then put its Client ID and Client Secret into '
     '<code>.env</code> in the project folder.',
     'cp .env.example .env'),
    ('Approve access once',
     'Open the printed link, approve, then copy the <code>code=</code> value from the address bar into '
     '<code>WHOOP_AUTH_CODE</code> in <code>.env</code>. The page you land on may not load; that is expected.',
     'python3 whoop.py --auth-url'),
    ('Pull your history',
     'Downloads everything WHOOP has scored for you and builds the dashboard. Later refreshes only fetch the '
     'last few days.',
     './refresh.sh'),
    ('Wear it for a night',
     'Your data is here, but nothing is scored yet. The dashboard needs one full night of sleep and a morning '
     'recovery score. Let WHOOP sync, then refresh.',
     './refresh.sh'),
]


def _env_has(path, *keys):
    """True when every key has a non-empty value in the .env file (values are never read out)."""
    found = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    found[k.strip()] = bool(v.strip().strip('"').strip("'"))
    except OSError:
        return False
    return all(found.get(k) for k in keys)


def progress(data_dir, env_path=None):
    """How many steps are done, read from the files on disk (0 to 3; the 4th is done when the build works)."""
    env_path = env_path or os.path.join(data_dir, '.env')
    done = [
        _env_has(env_path, 'WHOOP_CLIENT_ID', 'WHOOP_CLIENT_SECRET'),
        os.path.exists(os.path.join(data_dir, 'whoop_tokens.json')),
        os.path.exists(os.path.join(data_dir, 'whoop_data.json')),
    ]
    n = 0
    while n < len(done) and done[n]:
        n += 1
    return n


def render(data_dir, env_path=None):
    n_done = progress(data_dir, env_path)
    items = []
    for i, (title, text, cmd) in enumerate(STEPS):
        if i == 3 and n_done < 3:
            continue                          # "wear it for a night" only matters once data has been pulled
        if i == 2 and n_done == 3:
            continue                          # pulled already; the open step is the night's sleep
        state = 'done' if i < n_done else 'next' if i == n_done else 'todo'
        mark = '✓' if state == 'done' else str(len(items) + 1)
        tag = '<span class="tag">Next</span>' if state == 'next' else ''
        items.append(
            '<li class="step %s"><span class="mark" aria-hidden="true">%s</span><div class="body">'
            '<h2>%s %s</h2><p>%s</p><pre><code>%s</code></pre></div></li>' % (state, mark, title, tag, text, cmd))
    return PAGE.replace('__STEPS__', '\n'.join(items))


PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WHOOP Dashboard setup</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;800&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root{
    --bg:#0D1310; --surface:#141B17; --surface-2:#182019; --ink:#E9F0E9; --ink-muted:#93A092; --ink-faint:#717F70;
    --border:#26312A; --border-strong:#324033; --accent:#7C9EE8; --accent-ink:#0D1310; --accent-soft:#1E2A3E;
    --good:#4FAE7C; --good-bg:#16261E; --radius:18px;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;}
  body{background:var(--bg);
    background:radial-gradient(1100px 480px at 50% -200px, color-mix(in srgb, var(--accent) 8%, var(--bg)), var(--bg) 72%) no-repeat, var(--bg);
    color:var(--ink);font:15px/1.6 "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;padding:48px 20px 80px;
    -webkit-font-smoothing:antialiased;}
  main{max-width:640px;margin:0 auto;display:flex;flex-direction:column;gap:22px;}
  .eyebrow{font:700 12.5px "Archivo", sans-serif;letter-spacing:0.18em;text-transform:uppercase;color:var(--accent);}
  h1{font:800 clamp(26px, 5vw, 34px)/1.15 "Archivo", sans-serif;letter-spacing:-0.01em;margin:0;}
  .lead{color:var(--ink-muted);margin:0;max-width:56ch;}
  ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px;}
  .step{display:flex;gap:16px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;}
  .step.next{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft);}
  .step.done{opacity:.6;}
  .step.done p, .step.done pre{display:none;}
  .mark{flex-shrink:0;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font:500 13px "IBM Plex Mono", monospace;border:1px solid var(--border-strong);color:var(--ink-muted);}
  .next .mark{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);}
  .done .mark{background:var(--good-bg);border-color:var(--good);color:var(--good);}
  .body{min-width:0;flex:1;}
  h2{font:700 17px/1.3 "Archivo", sans-serif;margin:4px 0 0;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
  .tag{font:500 10px "IBM Plex Mono", monospace;letter-spacing:0.06em;text-transform:uppercase;color:var(--accent);
    background:var(--accent-soft);border-radius:100px;padding:3px 9px;}
  p{color:var(--ink-muted);margin:6px 0 10px;font-size:14px;}
  pre{margin:0;background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:10px 14px;overflow-x:auto;}
  code{font:13px "IBM Plex Mono", ui-monospace, monospace;color:var(--ink);}
  p code{background:var(--surface-2);border-radius:5px;padding:1px 5px;font-size:12.5px;}
  a{color:var(--accent);}
  .demo{border:1px dashed var(--border-strong);border-radius:var(--radius);padding:18px 22px;}
  .demo h2{font-size:15px;margin:0;}
  .foot{font-size:13px;color:var(--ink-faint);}
</style>
<main>
  <div class="eyebrow">WHOOP Dashboard</div>
  <h1>Let's connect your WHOOP.</h1>
  <p class="lead">Your data stays on this computer. Run each step in a terminal, inside the project folder,
  then reopen this page or the app.</p>
  <ol>
__STEPS__
  </ol>
  <div class="demo">
    <h2>Just looking? Open the demo</h2>
    <p>A synthetic athlete with 420 days of data. No WHOOP account needed.</p>
    <pre><code>python3 scripts/generate_demo_data.py demo
python3 build_dashboard.py demo
open demo/index.html</code></pre>
  </div>
  <p class="foot">Optional: add an OpenAI or Anthropic key to <code>.env</code> to ask questions about your data.
  Full guide in README.md.</p>
</main>
</html>
"""
