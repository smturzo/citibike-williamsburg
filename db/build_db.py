#!/usr/bin/env python3
"""Build data/citibike.db from the committed CSVs.

Idempotent: INSERT OR IGNORE against the primary key, so re-running is safe and
the duplicate buckets the two collectors produce collapse into one row.

The DB is a derived artifact and is gitignored. The CSVs are the source of truth
because they diff, merge, and compress; a SQLite binary does none of those.
"""
import csv, glob, gzip, json, os, sqlite3, sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import station_keys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NY = ZoneInfo("America/New_York")
DB = os.path.join(ROOT, "data", "citibike.db")


def main():
    st = json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]
    keys, added = station_keys.sync([s["station_id"] for s in st])
    if added:
        print(f"registered {added} new station key(s)")

    con = sqlite3.connect(DB)
    con.executescript(open(os.path.join(ROOT, "db", "schema.sql")).read())
    con.execute("PRAGMA journal_mode=WAL")
    cur = con.cursor()

    cur.executemany("INSERT OR REPLACE INTO stations VALUES (?,?,?,?,?,?,?,?)",
                    [(keys[s["station_id"]], s["station_id"], s["name"], s["short_name"],
                      s["lat"], s["lon"], s["capacity"], s["zone"]) for s in st])

    # Compacted days plus shards from days not yet compacted (including today).
    raw = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*.csv.gz"))) + \
          sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*", "*.csv")))

    n_snap = skipped = 0
    for path in raw:
        rows = []
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as f:
            for r in csv.DictReader(f):
                sid = keys.get(r["station_id"])
                if sid is None:
                    # A station that has since left the tracked set. Its history is
                    # still in the CSVs; it just isn't loaded.
                    skipped += 1
                    continue
                ts = int(r["ts_bucket"])
                dt = datetime.fromtimestamp(ts, NY)
                flags = (1 if int(r["is_renting"]) else 0) | (2 if int(r["is_returning"]) else 0)
                rows.append((
                    sid, dt.weekday(), dt.hour * 60 + dt.minute, ts,
                    int(r["bikes"]), int(r["ebikes"]), int(r["docks"]),
                    int(r["bikes_disabled"]), int(r["docks_disabled"]),
                    flags, max(ts - int(r["last_reported"]), 0),
                    int(dt.strftime("%Y%m%d%H")),
                ))
        cur.executemany("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        n_snap += len(rows)

    n_w = 0
    WCOLS = ["temp_f", "apparent_f", "precip_mm", "rain_mm", "snow_cm",
             "wind_kmh", "gust_kmh", "humidity", "cloud_pct", "weather_code"]
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "weather", "*.csv"))):
        with open(path) as f:
            rows = []
            for r in csv.DictReader(f):
                hk = int(r["hour_local"].replace("-", "").replace("T", "").replace(":", "")[:10])
                rows.append((hk, *[float(r[c]) if r[c] != "" else None for c in WCOLS]))
        cur.executemany("INSERT OR REPLACE INTO weather VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        n_w += len(rows)

    n_c = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "coverage", "*.csv"))):
        with open(path) as f:
            rows = []
            for r in csv.DictReader(f):
                ts = int(r["ts_bucket"])
                dt = datetime.fromtimestamp(ts, NY)
                rows.append((ts, r["src"], int(r["ok"]), int(r["n_stations"] or 0),
                             int(r["feed_last_updated"] or 0), int(r["fetch_ms"] or 0),
                             r["note"], dt.strftime("%Y-%m-%d"), dt.hour * 60 + dt.minute))
        cur.executemany("INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?,?)", rows)
        n_c += len(rows)

    con.commit()
    kept = cur.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    span = cur.execute("SELECT MIN(hour_key)/100, MAX(hour_key)/100 FROM snapshots").fetchone()
    con.execute("ANALYZE")
    con.commit()
    con.close()

    print(f"snapshots: {n_snap} csv rows -> {kept} unique  (dropped {n_snap - kept} dupes)"
          + (f", {skipped} untracked" if skipped else ""))
    print(f"weather:   {n_w} hours")
    print(f"coverage:  {n_c} poll attempts")
    print(f"span:      {span[0]} .. {span[1]}")
    sz = os.path.getsize(DB)
    print(f"db:        {DB} ({sz/1e6:.1f} MB"
          + (f", {sz/kept:.0f} bytes/row)" if kept else ")"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
