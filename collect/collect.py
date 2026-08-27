#!/usr/bin/env python3
"""Poll Citi Bike GBFS and append one snapshot row per tracked station.

Stdlib only, on purpose: this runs identically under launchd on macOS and on
GitHub Actions, so the two collectors stay byte-for-byte the same logic.

Rows are keyed on (ts_bucket, station_id) where ts_bucket is the poll time
floored to 5 minutes. Duplicate buckets from the two collectors are expected and
are deduplicated at DB build time - never here, because a collector that tried to
read back the whole day's file to dedupe would get slower every hour.

Each poll writes its own small immutable shard rather than appending to a daily
file. Appending would mean git storing a fresh copy of an ever-growing file 288
times a day; shards stay small, and compact.py folds finished days into one
gzipped file.

`--repeat N` takes N samples in one process, each aligned to a 5-minute bucket
boundary. This exists for GitHub Actions: GitHub decides when a run *starts*
(best-effort, drifting 5-20 minutes), but not what it does once running. A single
run taking six aligned samples converts an unpredictable start time into evenly
spaced data, which is the only way scheduler jitter stops corrupting a time grid
that distinguishes 16:50 from 17:20.

Usage: python3 collect/collect.py [--src mac|gha] [--repeat N]
"""
import argparse, csv, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_URL = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_status.json"
NY = ZoneInfo("America/New_York")
BUCKET_SEC = 300

FIELDS = ["ts_bucket", "station_id", "bikes", "ebikes", "classic", "docks",
          "bikes_disabled", "docks_disabled", "is_renting", "is_returning",
          "last_reported", "src"]
COV_FIELDS = ["ts_bucket", "src", "ok", "n_stations", "feed_last_updated", "fetch_ms", "note"]


def fetch(url, timeout=45, attempts=3):
    """GET with backoff. GBFS sits behind CloudFront and does occasionally 5xx."""
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "williamsburg-citibike/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def append_rows(path, fields, rows):
    """Append, writing a header if the file is new. Shards are written once, so
    for those this is effectively a create."""
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="mac", choices=["mac", "gha"])
    ap.add_argument("--repeat", type=int, default=1,
                    help="samples to take in one process, aligned to bucket boundaries")
    args = ap.parse_args()

    tracked = {s["station_id"]: s for s in
               json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]}

    rc = 0
    for i in range(max(args.repeat, 1)):
        if i:
            # Sleep to just past the next bucket boundary, so each sample lands in
            # its own bucket rather than two crowding into one.
            now = time.time()
            time.sleep(max(BUCKET_SEC - (now % BUCKET_SEC) + 2, 2))
        rc |= poll_once(tracked, args.src)
    return rc


def poll_once(tracked, src):
    now = int(time.time())
    bucket = now - (now % BUCKET_SEC)
    day = datetime.fromtimestamp(bucket, NY).strftime("%Y-%m-%d")
    month = day[:7]

    hhmm = datetime.fromtimestamp(bucket, NY).strftime("%H%M")
    raw_path = os.path.join(ROOT, "data", "raw", day, f"{hhmm}-{src}.csv")
    cov_path = os.path.join(ROOT, "data", "coverage", f"{month}.csv")

    t0 = time.time()
    try:
        data = fetch(STATUS_URL)
    except Exception as e:
        # Record the failed attempt. A missing coverage row and a failed one mean
        # different things downstream, and only one of them is our fault.
        append_rows(cov_path, COV_FIELDS, [{
            "ts_bucket": bucket, "src": src, "ok": 0, "n_stations": 0,
            "feed_last_updated": "", "fetch_ms": int((time.time() - t0) * 1000),
            "note": f"{type(e).__name__}: {e}"[:200]}])
        print(f"FETCH FAILED bucket={bucket}: {e}", file=sys.stderr)
        return 1
    fetch_ms = int((time.time() - t0) * 1000)

    rows = []
    for s in data["data"]["stations"]:
        sid = str(s["station_id"])
        if sid not in tracked:
            continue
        bikes = s.get("num_bikes_available", 0)
        ebikes = s.get("num_ebikes_available", 0)
        rows.append({
            "ts_bucket": bucket,
            "station_id": sid,
            "bikes": bikes,
            "ebikes": ebikes,
            "classic": max(bikes - ebikes, 0),
            "docks": s.get("num_docks_available", 0),
            "bikes_disabled": s.get("num_bikes_disabled", 0),
            "docks_disabled": s.get("num_docks_disabled", 0),
            "is_renting": s.get("is_renting", 0),
            "is_returning": s.get("is_returning", 0),
            # Kept so a stale feed can be told apart from a genuinely empty station.
            "last_reported": s.get("last_reported", 0),
            "src": src,
        })

    append_rows(raw_path, FIELDS, rows)
    append_rows(cov_path, COV_FIELDS, [{
        "ts_bucket": bucket, "src": src, "ok": 1, "n_stations": len(rows),
        "feed_last_updated": data.get("last_updated", ""), "fetch_ms": fetch_ms,
        "note": "" if len(rows) == len(tracked) else f"expected {len(tracked)}"}])

    stamp = datetime.fromtimestamp(bucket, NY).strftime("%Y-%m-%d %H:%M %Z")
    print(f"{stamp} src={src} stations={len(rows)}/{len(tracked)} "
          f"bikes={sum(r['bikes'] for r in rows)} ebikes={sum(r['ebikes'] for r in rows)} "
          f"docks={sum(r['docks'] for r in rows)} ({fetch_ms}ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
