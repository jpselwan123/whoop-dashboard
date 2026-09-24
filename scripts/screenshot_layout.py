"""Fingerprint the page's layout, so stale README screenshots fail a test instead of going unnoticed.

The screenshots show the sections in order with their headings and subtitles. When either changes, the
pictures are out of date. This records both, in order, in docs/screenshots/layout.txt at capture time;
tests/test_screenshots.py fails if the template no longer matches it.

Usage:  python3 scripts/screenshot_layout.py            print the current layout
        python3 scripts/screenshot_layout.py --write    record it (run right after new screenshots)
"""
import hashlib, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, 'dashboard_template.html')
LAYOUT = os.path.join(ROOT, 'docs', 'screenshots', 'layout.txt')


def current():
    """Every static section heading and subtitle in the page body, in order."""
    html = open(TEMPLATE).read()
    start = html.index('<div class="wrap">')          # the page's content column
    body = html[start:html.index('<script', start)]
    lines = []
    for m in re.finditer(r'<h2>(.*?)</h2>|<div class="section-sub"[^>]*>(.*?)</div>|<span class="glabel">(.*?)</span>',
                         body, re.S):
        text = re.sub(r'<[^>]+>', '', next(g for g in m.groups() if g is not None))
        kind = 'section' if m.group(1) is not None else 'group' if m.group(3) is not None else '  sub'
        lines.append('%s: %s' % (kind, ' '.join(text.split())))
    return lines


def fingerprint(lines):
    return hashlib.sha256('\n'.join(lines).encode()).hexdigest()[:16]


def recorded():
    try:
        text = open(LAYOUT).read().splitlines()
    except FileNotFoundError:
        return None
    return text[0].split()[-1] if text else None


if __name__ == '__main__':
    lines = current()
    if '--write' in sys.argv:
        with open(LAYOUT, 'w') as f:
            f.write('fingerprint %s\n' % fingerprint(lines))
            f.write('# the page layout these screenshots were taken from; regenerate both together\n')
            f.write('\n'.join(lines) + '\n')
        print('recorded', fingerprint(lines))
    else:
        print('\n'.join(lines))
        print('fingerprint', fingerprint(lines), '| recorded', recorded())
