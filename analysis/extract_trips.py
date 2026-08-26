#!/usr/bin/env python3
"""Filter a monthly Citi Bike trip archive down to trips touching our stations.

The published monthly files are ~1GB zipped and cover the whole system; the 195
stations we track are a small slice of that. This streams the CSVs straight out
of the zip (never extracting them to disk) and keeps only rides that start or end
in the tracked area, writing a slim gzipped file.

Join key is `short_name` ("5257.01"), which is what the trip archive puts in
start_station_id / end_station_id and what GBFS reports as short_name.

The ~1GB source zip is deleted once extraction succeeds - it is re-downloadable
from S3 at any time, and keeping 12 of them would blow the local storage budget
on its own. Pass --keep-zip to override.

Usage: python3 analysis/extract_trips.py data/trips/raw/202607.zip [--keep-zip]
"""
import csv, gzip, io, json, os, sys, zipfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "trips", "filtered")
OUT_COLS = ["rt", "started_at", "ended_at", "start_sid", "end_sid", "mc", "dur_s"]


def load_map():
    st = json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]
    by_short = {s["short_name"]: s["station_id"] for s in st}
    by_name = {s["name"]: s["station_id"] for s in st}
    return by_short, by_name


def parse_dur(a, b):
    """Duration in whole seconds, or '' if either timestamp is unparseable."""
    try:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in a else "%Y-%m-%d %H:%M:%S"
        fmt2 = "%Y-%m-%d %H:%M:%S.%f" if "." in b else "%Y-%m-%d %H:%M:%S"
        return int((datetime.strptime(b, fmt2) - datetime.strptime(a, fmt)).total_seconds())
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    zpath = sys.argv[1]
    keep_zip = "--keep-zip" in sys.argv
    month = os.path.basename(zpath).split(".")[0]
    by_short, by_name = load_map()

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{month}.csv.gz")

    z = zipfile.ZipFile(zpath)
    members = [i for i in z.infolist()
               if i.filename.endswith(".csv") and "__MACOSX" not in i.filename]

    total = kept = 0
    unmatched = Counter()
    stats = Counter()

    with gzip.open(out_path, "wt", newline="", compresslevel=6) as out:
        w = csv.writer(out)
        w.writerow(OUT_COLS)

        for m in members:
            with z.open(m) as fh:
                r = csv.reader(io.TextIOWrapper(fh, "utf-8", errors="replace"))
                header = next(r)
                ix = {c: i for i, c in enumerate(header)}
                need = ["rideable_type", "started_at", "ended_at", "start_station_name",
                        "start_station_id", "end_station_name", "end_station_id",
                        "member_casual"]
                if any(c not in ix for c in need):
                    print(f"  !! {m.filename}: unexpected columns, skipped", file=sys.stderr)
                    continue

                for row in r:
                    total += 1
                    if len(row) < len(header):
                        continue
                    ssid = by_short.get(row[ix["start_station_id"]]) \
                        or by_name.get(row[ix["start_station_name"]])
                    esid = by_short.get(row[ix["end_station_id"]]) \
                        or by_name.get(row[ix["end_station_name"]])
                    if not ssid and not esid:
                        continue

                    kept += 1
                    rt = "e" if row[ix["rideable_type"]] == "electric_bike" else "c"
                    mc = "m" if row[ix["member_casual"]] == "member" else "c"
                    a, b = row[ix["started_at"]], row[ix["ended_at"]]
                    w.writerow([rt, a, b, ssid or "", esid or "", mc, parse_dur(a, b)])

                    stats[f"rt_{rt}"] += 1
                    stats[f"mc_{mc}"] += 1
                    if ssid and esid:
                        stats["internal"] += 1
                    elif ssid:
                        stats["outbound"] += 1
                    else:
                        stats["inbound"] += 1
            print(f"  {m.filename}: {total:,} scanned, {kept:,} kept")

    print(f"\n{month}: {kept:,} / {total:,} trips touch the tracked area "
          f"({100*kept/max(total,1):.1f}%)")
    print(f"  e-bike {stats['rt_e']:,} ({100*stats['rt_e']/max(kept,1):.0f}%) · "
          f"classic {stats['rt_c']:,} ({100*stats['rt_c']/max(kept,1):.0f}%)")
    print(f"  member {stats['mc_m']:,} ({100*stats['mc_m']/max(kept,1):.0f}%) · "
          f"casual {stats['mc_c']:,}")
    print(f"  internal {stats['internal']:,} · outbound {stats['outbound']:,} · "
          f"inbound {stats['inbound']:,}")
    print(f"  -> {out_path} ({os.path.getsize(out_path)/1e6:.1f} MB)")

    z.close()
    if keep_zip:
        print(f"  kept {zpath} (--keep-zip)")
    else:
        n = os.path.getsize(zpath)
        os.remove(zpath)
        print(f"  removed {zpath} ({n/1e6:.0f} MB reclaimed; re-downloadable from S3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
