#!/bin/zsh
# Nightly: repair weather gaps, rebuild the DB, refresh dashboard stats.
set -e
cd "/Users/bargeen/Desktop/CitiBike"
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 collect/weather.py --days 7
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 db/build_db.py
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 analysis/build_stats.py
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 ops/health.py
