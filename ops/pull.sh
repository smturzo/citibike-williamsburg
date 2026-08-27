#!/usr/bin/env bash
# Pull the collected history from GitHub and rebuild a local database to work with.
#
# This is the whole local workflow now that collection runs in the cloud: you do
# not need anything running on this machine to keep the data flowing. Run this
# whenever you want to analyse; it is safe to run any time and re-runs cheaply.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="$(command -v python3)"

echo "== pulling =="
git pull --rebase --autostash origin main

echo "== rebuilding database =="
"$PY" db/build_db.py

echo "== refreshing stats =="
"$PY" analysis/build_stats.py

echo "== coverage =="
"$PY" ops/health.py | sed -n '/COVERAGE BY DAY/,/^$/p'

echo
echo "Ready. The database is at data/citibike.db - query it however you like:"
echo "  sqlite3 data/citibike.db"
echo "  python3 -c \"import sqlite3,pandas as pd; print(pd.read_sql('SELECT * FROM snapshots LIMIT 5', sqlite3.connect('data/citibike.db')))\""
