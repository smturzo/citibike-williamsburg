#!/usr/bin/env python3
"""Fold finished days of poll shards into one gzipped CSV per day.

288 shards/day is fine for git while a day is in progress, but not as permanent
history. Compacting to gzip cuts a day from ~4.6MB to a few hundred KB, which is
the difference between a repo that stays healthy for years and one that doesn't.

Only days strictly before today (America/New_York) are compacted, so an
in-progress day is never touched while collectors are still writing to it.
"""
import csv, glob, gzip, os, shutil, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NY = ZoneInfo("America/New_York")
RAW = os.path.join(ROOT, "data", "raw")
FIELDS = ["ts_bucket", "station_id", "bikes", "ebikes", "classic", "docks",
          "bikes_disabled", "docks_disabled", "is_renting", "is_returning",
          "last_reported", "src"]


def main():
    today = datetime.now(NY).strftime("%Y-%m-%d")
    days = sorted(d for d in os.listdir(RAW)
                  if os.path.isdir(os.path.join(RAW, d)) and d < today)
    if not days:
        print("nothing to compact")
        return 0

    for day in days:
        ddir = os.path.join(RAW, day)
        out = os.path.join(RAW, f"{day}.csv.gz")
        seen, rows = set(), []

        # Existing compacted file first, so re-running after a late shard arrives
        # merges rather than overwrites.
        if os.path.exists(out):
            with gzip.open(out, "rt") as f:
                for r in csv.DictReader(f):
                    k = (r["ts_bucket"], r["station_id"])
                    if k not in seen:
                        seen.add(k)
                        rows.append(r)

        shards = sorted(glob.glob(os.path.join(ddir, "*.csv")))
        for path in shards:
            with open(path) as f:
                for r in csv.DictReader(f):
                    k = (r["ts_bucket"], r["station_id"])
                    if k not in seen:
                        seen.add(k)
                        rows.append(r)

        rows.sort(key=lambda r: (int(r["ts_bucket"]), r["station_id"]))
        tmp = out + ".tmp"
        with gzip.open(tmp, "wt", newline="", compresslevel=9) as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, out)
        shutil.rmtree(ddir)

        buckets = len({r["ts_bucket"] for r in rows})
        print(f"{day}: {len(shards)} shards -> {len(rows)} rows, {buckets} buckets, "
              f"{os.path.getsize(out)/1e3:.0f} KB gz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
