#!/bin/bash
# Double-click to serve Week Prep on your local network (see serve.py for options).
cd "$(dirname "$0")"
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" serve.py "$@"
read -n1 -r -p "Server stopped. Press any key to close..." _ || true
