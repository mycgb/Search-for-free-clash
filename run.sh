#!/usr/bin/env sh
# Portable launcher for Linux / macOS.
# Needs Python 3.8+; tkinter is optional (browser UI fallback is built in).
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3.8+ is required. Install it and retry."
    exit 1
fi

exec "$PY" node_searcher.py
