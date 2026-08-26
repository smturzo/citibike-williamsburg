#!/usr/bin/env python3
"""Report current and projected storage against the two hard budgets.

  GitHub repo : 1.0 GB  - GitHub's own recommended ceiling. They warn above this,
                          and performance degrades well before the 5GB hard stop.
  Local disk  : 3.0 GB  - set by the project owner.

Projections use measured rates, not guesses:
  * 33 bytes/row in SQLite      (measured, schema v2, 56,160-row day)
  * 6.7 bytes/row compacted gz  (measured, real shards at compresslevel 9)
  * 22.1 MB/month filtered trips (measured, July 2026)

Run with --fail-over-budget to exit nonzero when a 12-month projection breaches a
budget. The daily workflow does exactly that, so drift surfaces as a failed run
rather than as a surprise a year from now.

Usage: python3 ops/sizecheck.py [--fail-over-budget] [--months 12]
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB_BUDGET = 1.0 * 1e9
LOCAL_BUDGET = 3.0 * 1e9

ROWS_PER_DAY = 195 * 288        # stations x 5-min buckets
DB_BYTES_PER_ROW = 33
GZ_BYTES_PER_ROW = 6.7
TRIPS_MB_PER_MONTH = 22.1


def du(path):
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(path) for f in fs
               if os.path.exists(os.path.join(dp, f)))


def gb(n):
    return f"{n/1e9:6.2f} GB" if n >= 1e9 else f"{n/1e6:6.1f} MB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-over-budget", action="store_true")
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args()
    days = a.months * 30.44

    git_dir = du(os.path.join(ROOT, ".git"))
    raw_gz = du(os.path.join(ROOT, "data", "raw"))
    trips_f = du(os.path.join(ROOT, "data", "trips", "filtered"))
    trips_r = du(os.path.join(ROOT, "data", "trips", "raw"))
    db = du(os.path.join(ROOT, "data", "citibike.db")) \
       + du(os.path.join(ROOT, "data", "citibike.db-wal"))
    weather = du(os.path.join(ROOT, "data", "weather"))
    coverage = du(os.path.join(ROOT, "data", "coverage"))

    # Projected 12-month totals.
    p_gz = ROWS_PER_DAY * GZ_BYTES_PER_ROW * days
    p_db = ROWS_PER_DAY * DB_BYTES_PER_ROW * days
    p_trips = TRIPS_MB_PER_MONTH * 1e6 * a.months
    p_cov = 288 * 2 * 60 * days          # ~60 bytes per coverage row, 2 sources
    p_wx = 24 * 120 * days               # ~120 bytes per weather hour
    p_repo = p_gz + p_trips + p_cov + p_wx
    p_local = p_repo + p_db

    print("=" * 64)
    print(f"CURRENT")
    print("=" * 64)
    for label, v in [(".git history", git_dir), ("data/raw (compacted)", raw_gz),
                     ("trips (filtered)", trips_f), ("trips (raw zips)", trips_r),
                     ("weather", weather), ("coverage", coverage),
                     ("citibike.db (local only)", db)]:
        print(f"  {label:26s} {gb(v)}")
    print(f"  {'-'*26} {'-'*9}")
    print(f"  {'total on disk':26s} {gb(git_dir + raw_gz + trips_f + trips_r + weather + coverage + db)}")

    print()
    print("=" * 64)
    print(f"PROJECTED AT {a.months} MONTHS")
    print("=" * 64)
    print(f"  compacted snapshots        {gb(p_gz)}")
    print(f"  filtered trips             {gb(p_trips)}")
    print(f"  weather + coverage         {gb(p_cov + p_wx)}")
    print(f"  {'-'*26} {'-'*9}")
    ok_repo = p_repo <= GITHUB_BUDGET
    ok_local = p_local <= LOCAL_BUDGET
    print(f"  GITHUB REPO                {gb(p_repo)}  / {gb(GITHUB_BUDGET)} budget"
          f"   [{'OK' if ok_repo else 'OVER'}]  {100*p_repo/GITHUB_BUDGET:.0f}% used")
    print(f"  + citibike.db              {gb(p_db)}")
    print(f"  LOCAL TOTAL                {gb(p_local)}  / {gb(LOCAL_BUDGET)} budget"
          f"   [{'OK' if ok_local else 'OVER'}]  {100*p_local/LOCAL_BUDGET:.0f}% used")

    if trips_r > 0:
        print()
        print(f"  NOTE: {gb(trips_r)} of raw trip zips are on disk. These are")
        print(f"        re-downloadable and are not counted in the projection.")
        print(f"        Remove with: rm -rf data/trips/raw/*.zip")

    if a.fail_over_budget and not (ok_repo and ok_local):
        print("\nOVER BUDGET", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
