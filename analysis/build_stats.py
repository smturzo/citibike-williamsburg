#!/usr/bin/env python3
"""Aggregate snapshots into the day x time grid the dashboard reads.

Produces docs/data/stats.json: for every tracked station, at every (weekday,
target time) slot, the probability that you'd find a classic bike, an e-bike, and
a free dock.

Three deliberate choices:

1. ONE pass over snapshots, grouped by (sid, dow, mod), and the +/-7 minute
   windows are summed in Python afterwards. The old version ran a query per slot;
   under the v2 primary key (which leads with sid) each of those would degrade
   into a full table scan, 135 times over.

2. Each target time aggregates a window, not an exact instant. A single 5-minute
   bucket on 5 Fridays is 5 observations, which is not enough to estimate a
   probability from.

3. Probabilities are Laplace-smoothed. With few observations a raw rate reports
   0.00 or 1.00 far too confidently - "this station is ALWAYS empty" off three
   samples is exactly the kind of claim that survives into a conclusion it
   shouldn't. `n` is published alongside so thin slots can be greyed out.
"""
import json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "citibike.db")
OUT = os.path.join(ROOT, "docs", "data", "stats.json")

TARGET_TIMES = [
    (7, 0), (8, 0), (9, 0), (10, 0), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0),
    (16, 0), (16, 30), (16, 50), (17, 0), (17, 20), (17, 30), (18, 0), (18, 30),
    (19, 0), (19, 30), (20, 0), (21, 0), (21, 30), (22, 0), (23, 0),
    (0, 0), (0, 30), (1, 0),
]
TARGET_DOWS = [0, 2, 4, 5, 6]
DOW_NAMES = {0: "Mon", 2: "Wed", 4: "Fri", 5: "Sat", 6: "Sun"}
WINDOW = 7
MIN_N = 8
ALPHA = 1.0
BUCKET = 5      # minutes between snapshots


def main():
    if not os.path.exists(DB):
        print("no database yet - run db/build_db.py first", file=sys.stderr)
        return 1
    con = sqlite3.connect(DB)

    sid_to_station = {r[0]: r[1] for r in con.execute("SELECT sid, station_id FROM stations")}

    # Single scan. flags = 3 means renting AND returning: a station out of service
    # is not a data point about demand.
    agg = {}
    for row in con.execute("""
        SELECT sid, dow, mod,
               COUNT(*), SUM(bikes - ebikes > 0), SUM(ebikes > 0), SUM(docks > 0),
               SUM(bikes - ebikes), SUM(ebikes), SUM(docks)
        FROM snapshots WHERE flags = 3
        GROUP BY sid, dow, mod
    """):
        agg[(row[0], row[1], row[2])] = row[3:]

    slots = [(d, h * 60 + m) for d in TARGET_DOWS for (h, m) in TARGET_TIMES]
    offsets = [o for o in range(-WINDOW, WINDOW + 1) if o % BUCKET == 0]

    blank = lambda: {"n": [0] * len(slots), "pc": [None] * len(slots),
                     "pe": [None] * len(slots), "pd": [None] * len(slots),
                     "mb": [None] * len(slots), "me": [None] * len(slots),
                     "md": [None] * len(slots)}
    out = {sid_to_station[s]: blank() for s in sid_to_station}

    for i, (dow, mod) in enumerate(slots):
        for sid, station_id in sid_to_station.items():
            n = ch = eh = dh = sb = se = sd = 0
            for o in offsets:
                a = agg.get((sid, dow, (mod + o) % 1440))
                if a:
                    n += a[0]; ch += a[1]; eh += a[2]; dh += a[3]
                    sb += a[4]; se += a[5]; sd += a[6]
            if not n:
                continue
            s = out[station_id]
            s["n"][i] = n
            s["pc"][i] = round((ch + ALPHA) / (n + 2 * ALPHA), 3)
            s["pe"][i] = round((eh + ALPHA) / (n + 2 * ALPHA), 3)
            s["pd"][i] = round((dh + ALPHA) / (n + 2 * ALPHA), 3)
            s["mb"][i] = round(sb / n, 1)
            s["me"][i] = round(se / n, 1)
            s["md"][i] = round(sd / n, 1)

    days = con.execute("SELECT COUNT(DISTINCT hour_key/100) FROM snapshots").fetchone()[0]
    span = con.execute("SELECT MIN(hour_key)/100, MAX(hour_key)/100 FROM snapshots").fetchone()
    total = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    con.close()

    fmt = lambda d: f"{d//10000}-{(d//100)%100:02d}-{d%100:02d}" if d else None
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_date": fmt(span[0]), "last_date": fmt(span[1]), "n_days": days,
        "n_observations": total, "min_n": MIN_N, "window_min": WINDOW,
        "dows": TARGET_DOWS, "dow_names": DOW_NAMES,
        "times": [f"{h:02d}:{m:02d}" for (h, m) in TARGET_TIMES],
        "slots": [[d, t] for (d, t) in slots],
        "stations": out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    filled = sum(1 for s in out.values() for n in s["n"] if n >= MIN_N)
    tot = len(out) * len(slots)
    print(f"stats.json: {len(out)} stations x {len(slots)} slots")
    print(f"  days covered : {days} ({fmt(span[0])} .. {fmt(span[1])})")
    print(f"  observations : {total:,}")
    print(f"  slots with n>={MIN_N}: {filled}/{tot} ({100*filled/tot:.1f}%)")
    print(f"  size         : {os.path.getsize(OUT)/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
