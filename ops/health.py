#!/usr/bin/env python3
"""Coverage report: how much of the intended 5-minute grid actually got captured.

The point of this script is to make gaps legible. A sleeping laptop and a quiet
night produce identical-looking absences in the raw data, and mistaking one for
the other is the single most likely way this project reaches a wrong conclusion.

Everything here reads the `coverage` table, not `snapshots` - coverage has one
row per poll attempt rather than 195, so this stays instant no matter how much
history accumulates, and it can see attempts that FAILED, which snapshots cannot.
"""
import os, sqlite3, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "citibike.db")
NY = ZoneInfo("America/New_York")
EXPECTED_PER_DAY = 288


def bar(frac, width=28):
    return "#" * int(round(frac * width)) + "." * (width - int(round(frac * width)))


def main():
    if not os.path.exists(DB):
        print("no database yet", file=sys.stderr)
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print("=" * 62)
    print("COVERAGE BY DAY")
    print("=" * 62)
    rows = con.execute("""
        SELECT local_date, COUNT(DISTINCT ts_bucket) AS buckets
        FROM coverage WHERE ok = 1
        GROUP BY local_date ORDER BY local_date DESC LIMIT 21
    """).fetchall()
    if not rows:
        print("  no successful polls yet")
    for r in rows:
        frac = min(r["buckets"] / EXPECTED_PER_DAY, 1.0)
        print(f"  {r['local_date']}  {bar(frac)}  {r['buckets']:3d}/288 ({100*frac:5.1f}%)")

    print()
    print("=" * 62)
    print("COVERAGE BY HOUR  (all days pooled - shows *when* we go blind)")
    print("=" * 62)
    hours = {r["h"]: r["n"] for r in con.execute(
        "SELECT mod/60 AS h, COUNT(DISTINCT ts_bucket) AS n "
        "FROM coverage WHERE ok=1 GROUP BY h")}
    n_days = con.execute(
        "SELECT COUNT(DISTINCT local_date) FROM coverage WHERE ok=1").fetchone()[0] or 1
    for h in range(24):
        frac = min(hours.get(h, 0) / (12 * n_days), 1.0)
        print(f"  {h:02d}:00  {bar(frac)}  {100*frac:5.1f}%"
              + ("  <-- blind" if frac < 0.5 else ""))

    print()
    print("=" * 62)
    print("COLLECTOR HEALTH")
    print("=" * 62)
    for r in con.execute("""SELECT src, COUNT(*) AS attempts, SUM(ok) AS good,
                                   AVG(fetch_ms) AS ms FROM coverage GROUP BY src"""):
        print(f"  {r['src']:4s}  {r['attempts']:6d} attempts  "
              f"{r['attempts'] - (r['good'] or 0):3d} failed  avg {r['ms']:.0f}ms")

    for r in con.execute("SELECT ts_bucket, src, note FROM coverage WHERE ok=0 "
                         "ORDER BY ts_bucket DESC LIMIT 5"):
        t = datetime.fromtimestamp(r["ts_bucket"], NY).strftime("%m-%d %H:%M")
        print(f"    FAIL {t} [{r['src']}] {(r['note'] or '')[:60]}")

    buckets = [r[0] for r in con.execute(
        "SELECT DISTINCT ts_bucket FROM coverage WHERE ok=1 ORDER BY ts_bucket")]
    if len(buckets) > 1:
        gaps = sorted(((b - a, a, b) for a, b in zip(buckets, buckets[1:]) if b - a > 600),
                      reverse=True)
        print()
        print("=" * 62)
        print(f"LARGEST GAPS  ({len(gaps)} gaps > 10 min)")
        print("=" * 62)
        for dur, a, b in gaps[:8]:
            t0 = datetime.fromtimestamp(a, NY).strftime("%m-%d %H:%M")
            t1 = datetime.fromtimestamp(b, NY).strftime("%m-%d %H:%M")
            print(f"  {dur//3600:3d}h{(dur%3600)//60:02d}m   {t0} -> {t1}")
        if not gaps:
            print("  none - unbroken coverage")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
