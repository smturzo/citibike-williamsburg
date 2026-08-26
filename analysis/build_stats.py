#!/usr/bin/env python3
"""Aggregate snapshots into the day x time grid the dashboard reads.

Produces docs/data/stats.json: for every tracked station, at every (weekday,
target time) slot, the probability that you'd find a classic bike, an e-bike, and
a free dock.

Two deliberate choices:

1. Each target time aggregates a +/-7 minute window, not an exact instant. A
   single 5-minute bucket on 5 Fridays is 5 observations, which is not enough to
   estimate a probability. The window trades a little time resolution for
   estimates that are actually stable.

2. Probabilities use a Laplace-smoothed estimate. With few observations, a raw
   rate reports 0.00 or 1.00 far too confidently - "this station is ALWAYS empty"
   off three samples is exactly the kind of claim that survives into a conclusion
   it shouldn't. Smoothing pulls thin evidence toward 0.5; `n` is published
   alongside so the dashboard can grey out slots that remain too thin to trust.
"""
import json, os, sqlite3, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "citibike.db")
OUT = os.path.join(ROOT, "docs", "data", "stats.json")

# The times asked for, as minutes since local midnight.
TARGET_TIMES = [
    (7, 0), (8, 0), (9, 0), (10, 0), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0),
    (16, 0), (16, 30), (16, 50), (17, 0), (17, 20), (17, 30), (18, 0), (18, 30),
    (19, 0), (19, 30), (20, 0), (21, 0), (21, 30), (22, 0), (23, 0),
    (0, 0), (0, 30), (1, 0),
]
TARGET_DOWS = [0, 2, 4, 5, 6]          # Mon, Wed, Fri, Sat, Sun
DOW_NAMES = {0: "Mon", 2: "Wed", 4: "Fri", 5: "Sat", 6: "Sun"}
WINDOW = 7                              # minutes either side
MIN_N = 8                               # below this the dashboard marks a slot thin
ALPHA = 1.0                             # Laplace pseudo-counts


def smoothed(hits, n):
    return (hits + ALPHA) / (n + 2 * ALPHA) if n else None


def main():
    if not os.path.exists(DB):
        print("no database yet - run db/build_db.py first", file=sys.stderr)
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    stations = {r["station_id"]: dict(r) for r in
                con.execute("SELECT * FROM stations").fetchall()}

    slots = [(d, h * 60 + m) for d in TARGET_DOWS for (h, m) in TARGET_TIMES]
    slot_ix = {s: i for i, s in enumerate(slots)}

    blank = lambda: {"n": [0] * len(slots), "pc": [None] * len(slots),
                     "pe": [None] * len(slots), "pd": [None] * len(slots),
                     "mb": [None] * len(slots), "me": [None] * len(slots),
                     "md": [None] * len(slots)}
    out = {sid: blank() for sid in stations}

    # One pass per slot: the (station_id, dow, mod) index makes each of these a
    # range scan rather than a table scan.
    for (dow, mod) in slots:
        i = slot_ix[(dow, mod)]
        lo, hi = mod - WINDOW, mod + WINDOW
        if lo < 0 or hi >= 1440:
            # A window straddling midnight wraps to the other end of the day.
            cond = "(mod >= ? OR mod <= ?)"
            args = (lo % 1440, hi % 1440)
        else:
            cond = "(mod BETWEEN ? AND ?)"
            args = (lo, hi)

        q = f"""
            SELECT station_id,
                   COUNT(*)                          AS n,
                   SUM(classic > 0)                  AS c_hit,
                   SUM(ebikes  > 0)                  AS e_hit,
                   SUM(docks   > 0)                  AS d_hit,
                   AVG(classic) AS mb, AVG(ebikes) AS me, AVG(docks) AS md
            FROM snapshots
            WHERE dow = ? AND {cond}
              AND is_renting = 1          -- a station out of service is not a
              AND is_returning = 1        -- data point about demand
            GROUP BY station_id
        """
        for r in con.execute(q, (dow, *args)):
            sid = r["station_id"]
            if sid not in out:
                continue
            s, n = out[sid], r["n"]
            s["n"][i] = n
            s["pc"][i] = round(smoothed(r["c_hit"], n), 3)
            s["pe"][i] = round(smoothed(r["e_hit"], n), 3)
            s["pd"][i] = round(smoothed(r["d_hit"], n), 3)
            s["mb"][i] = round(r["mb"], 1)
            s["me"][i] = round(r["me"], 1)
            s["md"][i] = round(r["md"], 1)

    span = con.execute("SELECT MIN(local_date), MAX(local_date), "
                       "COUNT(DISTINCT local_date) FROM snapshots").fetchone()
    total = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    con.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_date": span[0], "last_date": span[1], "n_days": span[2],
        "n_observations": total,
        "min_n": MIN_N,
        "window_min": WINDOW,
        "dows": TARGET_DOWS,
        "dow_names": DOW_NAMES,
        "times": [f"{h:02d}:{m:02d}" for (h, m) in TARGET_TIMES],
        "slots": [[d, t] for (d, t) in slots],
        "stations": out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    filled = sum(1 for s in out.values() for n in s["n"] if n >= MIN_N)
    print(f"stats.json: {len(out)} stations x {len(slots)} slots")
    print(f"  days covered : {span[2]} ({span[0]} .. {span[1]})")
    print(f"  observations : {total}")
    print(f"  slots with n>={MIN_N}: {filled}/{len(out) * len(slots)} "
          f"({100 * filled / (len(out) * len(slots)):.1f}%)")
    print(f"  size         : {os.path.getsize(OUT)/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
