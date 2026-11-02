#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! python3 whoop.py; then
  # Nothing pulled yet (first run, setup unfinished): still write index.html, which then shows the
  # setup steps. With data on disk the existing dashboard is left exactly as it was.
  [ -f whoop_data.json ] || python3 build_dashboard.py >/dev/null 2>&1 || true
  exit 1
fi
python3 build_dashboard.py
echo "Reload index.html in your browser to see the update."
