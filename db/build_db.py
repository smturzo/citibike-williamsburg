#!/usr/bin/env python3
"""Build data/citibike.db from the committed CSVs.

Idempotent: INSERT OR IGNORE against the (ts_bucket, station_id) primary key, so
re-running is safe and the duplicate buckets the two collectors produce collapse
into one row. The DB is a derived artifact and is gitignored - the CSVs are the
source of truth, because they diff and merge and the SQLite binary does not.
"""
import csv, glob, gzip, json, os, sqlite3, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NY = ZoneInfo("America/New_York")
DB = os.path.join(ROOT, "data", "citibike.db")

SNAP_COLS = ["ts_bucket", "station_id", "bikes", "ebikes", "classic", "docks",
             "bikes_disabled", "docks_disabled", "is_renting", "is_returning",
             "last_reported", "src", "local_date", "dow", "mod", "hour_local"]
INT_COLS = {"ts_bucket", "bikes", "ebikes", "classic", "docks", "bikes_disabled",
            "docks_disabled", "is_renting", "is_returning", "last_reported"}


def main():
    con = sqlite3.connect(DB)
    con.executescript(open(os.path.join(ROOT, "db", "schema.sql")).read())
    con.execute("PRAGMA journal_mode=WAL")
    cur = con.cursor()

    st = json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]
    cur.executemany(
        "INSERT OR REPLACE INTO stations VALUES (?,?,?,?,?,?,?)",
        [(s["station_id"], s["name"], s["short_name"], s["lat"], s["lon"],
          s["capacity"], s["zone"]) for s in st])

    # Compacted days plus any shards from days not yet compacted (incl. today).
    raw = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*.csv.gz"))) + \
          sorted(glob.glob(os.path.join(ROOT, "data", "raw", "*", "*.csv")))

    n_snap = 0
    for path in raw:
        rows = []
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as f:
            for r in csv.DictReader(f):
                ts = int(r["ts_bucket"])
                dt = datetime.fromtimestamp(ts, NY)
                r["local_date"] = dt.strftime("%Y-%m-%d")
                r["dow"] = dt.weekday()
                r["mod"] = dt.hour * 60 + dt.minute
                r["hour_local"] = dt.strftime("%Y-%m-%dT%H:00")
                for k in INT_COLS:
                    r[k] = int(r[k])
                rows.append(tuple(r[c] for c in SNAP_COLS))
        cur.executemany(
            f"INSERT OR IGNORE INTO snapshots VALUES ({','.join('?' * len(SNAP_COLS))})", rows)
        n_snap += len(rows)

    n_w = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "weather", "*.csv"))):
        with open(path) as f:
            rows = [tuple(r[c] if r[c] != "" else None for c in
                          ["hour_local", "temp_f", "apparent_f", "precip_mm", "rain_mm",
                           "snow_cm", "wind_kmh", "gust_kmh", "humidity", "cloud_pct",
                           "weather_code"]) for r in csv.DictReader(f)]
        cur.executemany("INSERT OR REPLACE INTO weather VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        n_w += len(rows)

    n_c = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "coverage", "*.csv"))):
        with open(path) as f:
            rows = [(int(r["ts_bucket"]), r["src"], int(r["ok"]),
                     int(r["n_stations"] or 0), int(r["feed_last_updated"] or 0),
                     int(r["fetch_ms"] or 0), r["note"]) for r in csv.DictReader(f)]
        cur.executemany("INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?)", rows)
        n_c += len(rows)

    con.commit()
    kept = cur.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    span = cur.execute("SELECT MIN(local_date), MAX(local_date) FROM snapshots").fetchone()
    con.execute("ANALYZE")
    con.commit()
    con.close()

    print(f"snapshots: {n_snap} csv rows -> {kept} unique  (dropped {n_snap - kept} dupes)")
    print(f"weather:   {n_w} hours")
    print(f"coverage:  {n_c} poll attempts")
    print(f"span:      {span[0]} .. {span[1]}")
    print(f"db:        {DB} ({os.path.getsize(DB) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
