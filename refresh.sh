#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 whoop.py
python3 build_dashboard.py
echo "Reload index.html in your browser to see the update."
