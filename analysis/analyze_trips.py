#!/usr/bin/env python3
"""Turn filtered trip archives into per-station demand and net-flow statistics.

The trip archive answers a question live polling cannot: *how much demand is
there*, and *which direction is it flowing*. A station that sends far more rides
than it receives at 5pm will be empty at 5pm no matter how often we poll it -
this is the mechanism behind the availability patterns, not just the symptom.

The reverse matters just as much: a strong net receiver fills up, and the problem
there is finding a free dock, not finding a bike.

Note what this data cannot tell you: a ride that never happened because no bike
was there leaves no record. Demand here is *satisfied* demand, so a station that
looks quiet may be starved rather than unpopular. Live dock data is what
distinguishes those, which is why both halves of this project exist.

Outputs docs/data/trips.json for the dashboard, plus a terminal report.
"""
import csv, glob, gzip, json, os, sys
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "trips.json")

TARGET_TIMES = [
    (7, 0), (8, 0), (9, 0), (10, 0), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0),
    (16, 0), (16, 30), (16, 50), (17, 0), (17, 20), (17, 30), (18, 0), (18, 30),
    (19, 0), (19, 30), (20, 0), (21, 0), (21, 30), (22, 0), (23, 0),
    (0, 0), (0, 30), (1, 0),
]
TARGET_DOWS = [0, 2, 4, 5, 6]
DOW_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
WINDOW = 15          # +/- minutes summed around each target time
BIN = 5              # aggregation resolution, minutes

_dcache = {}


def dow_of(s):
    """Weekday from a 'YYYY-MM-DD...' prefix, cached - there are only ~120
    distinct dates but millions of rows."""
    k = s[:10]
    d = _dcache.get(k)
    if d is None:
        d = date(int(k[:4]), int(k[5:7]), int(k[8:10])).weekday()
        _dcache[k] = d
    return d


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "trips", "filtered", "*.csv.gz")))
    if not files:
        print("no filtered trip files - run analysis/fetch_trips.sh first", file=sys.stderr)
        return 1

    stations = {s["station_id"]: s for s in
                json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]}

    # (station_id, dow, bin) -> [departures, dep_ebike, arrivals, arr_ebike]
    cell = defaultdict(lambda: [0, 0, 0, 0])
    dates_by_dow = defaultdict(set)
    pairs = defaultdict(int)
    hourly = defaultdict(lambda: [0, 0])      # (dow, hour) -> [rides, ebike]
    n = 0

    for path in files:
        with gzip.open(path, "rt") as f:
            r = csv.reader(f)
            next(r)
            for rt, sa, ea, ssid, esid, mc, dur in r:
                n += 1
                d = dow_of(sa)
                dates_by_dow[d].add(sa[:10])
                b = ((int(sa[11:13]) * 60 + int(sa[14:16])) // BIN) * BIN
                is_e = rt == "e"
                if ssid:
                    c = cell[(ssid, d, b)]
                    c[0] += 1
                    c[1] += is_e
                if esid:
                    # Arrivals are binned by END time - that's when the dock is taken.
                    de = dow_of(ea)
                    be = ((int(ea[11:13]) * 60 + int(ea[14:16])) // BIN) * BIN
                    c = cell[(esid, de, be)]
                    c[2] += 1
                    c[3] += is_e
                if ssid and esid and ssid != esid:
                    pairs[(ssid, esid)] += 1
                hourly[(d, int(sa[11:13]))][0] += 1
                hourly[(d, int(sa[11:13]))][1] += is_e
        print(f"  read {os.path.basename(path)}  (running total {n:,} trips)")

    n_days = {d: len(v) for d, v in dates_by_dow.items()}
    print(f"\n{n:,} trips across {sum(n_days.values())} days")
    print("  days per weekday: " + ", ".join(
        f"{DOW_NAMES[d]} {n_days.get(d,0)}" for d in range(7)))

    slots = [(d, h * 60 + m) for d in TARGET_DOWS for (h, m) in TARGET_TIMES]
    offs = [o for o in range(-WINDOW, WINDOW + 1) if o % BIN == 0]

    out = {}
    for sid in stations:
        dep, arr, net, esh = [], [], [], []
        for (d, mod) in slots:
            D = A = DE = 0
            for o in offs:
                c = cell.get((sid, d, (mod + o) % 1440))
                if c:
                    D += c[0]; A += c[2]; DE += c[1]
            days = n_days.get(d, 0) or 1
            dep.append(round(D / days, 2))
            arr.append(round(A / days, 2))
            net.append(round((A - D) / days, 2))
            esh.append(round(DE / D, 2) if D else None)
        out[sid] = {"dep": dep, "arr": arr, "net": net, "esh": esh}

    payload = {
        "months": [os.path.basename(p).split(".")[0] for p in files],
        "n_trips": n, "n_days": n_days,
        "window_min": WINDOW,
        "dows": TARGET_DOWS, "dow_names": {str(k): v for k, v in DOW_NAMES.items()},
        "times": [f"{h:02d}:{m:02d}" for (h, m) in TARGET_TIMES],
        "slots": [[d, t] for (d, t) in slots],
        "stations": out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"-> {OUT} ({os.path.getsize(OUT)/1e6:.2f} MB)")

    # ---- report -------------------------------------------------------------
    def slot_ix(d, h, m):
        return slots.index((d, h * 60 + m))

    def report(title, d, h, m, key, reverse=True, k=8):
        i = slot_ix(d, h, m)
        rows = [(out[s][key][i], stations[s]["name"], out[s]["dep"][i], out[s]["arr"][i])
                for s in out]
        rows.sort(reverse=reverse)
        print(f"\n{title}")
        print(f"  {'station':34s} {'net/day':>8s} {'out':>7s} {'in':>7s}")
        for v, nm, dp, ar in rows[:k]:
            print(f"  {nm[:34]:34s} {v:+8.1f} {dp:7.1f} {ar:7.1f}")

    print("\n" + "=" * 62)
    print(f"RUSH HOUR — Friday 17:20 (±{WINDOW}min), rides per day")
    print("=" * 62)
    report("NET DRAIN  (bikes leave — hard to GET a bike)", 4, 17, 20, "net", reverse=False)
    report("NET FILL   (bikes arrive — hard to find a DOCK)", 4, 17, 20, "net", reverse=True)

    print("\n" + "=" * 62)
    print("SYSTEM-WIDE HOURLY PROFILE (rides/day, e-bike share)")
    print("=" * 62)
    for d in TARGET_DOWS:
        days = n_days.get(d, 0) or 1
        peak = max(range(24), key=lambda h: hourly[(d, h)][0])
        tot = sum(hourly[(d, h)][0] for h in range(24)) / days
        pe = hourly[(d, peak)]
        print(f"  {DOW_NAMES[d]}  {tot:7.0f} rides/day   peak {peak:02d}:00 "
              f"({pe[0]/days:5.0f}/day, {100*pe[1]/max(pe[0],1):.0f}% e-bike)")

    # ---- cumulative pressure ------------------------------------------------
    # Net flow within any one 30-minute window is small next to a 40-79 dock
    # station, so it cannot by itself explain an empty rack. What does is the
    # SUM of that flow across the day: a station bleeding 2 bikes an hour from
    # 7am is 20 down by evening.
    #
    # Read this as demand pressure, not as the actual bike count. Rebalancing
    # trucks push against it all day, and that traffic leaves no trip record.
    # A deep drawdown means "this station needs constant resupply to stay
    # usable", which is exactly the station you don't want to rely on.
    print("\n" + "=" * 62)
    print("CUMULATIVE DEMAND PRESSURE — Friday, from 05:00")
    print("=" * 62)
    curves = {}
    for sid in stations:
        days = n_days.get(4, 0) or 1
        run, series = 0.0, []
        for b in range(300, 1440, BIN):          # 05:00 -> midnight
            c = cell.get((sid, 4, b))
            if c:
                run += (c[2] - c[0]) / days
            series.append((b, run))
        curves[sid] = series

    def trough(sid):
        return min(curves[sid], key=lambda x: x[1])

    def crest(sid):
        return max(curves[sid], key=lambda x: x[1])

    drained = sorted(stations, key=lambda s: trough(s)[1])[:8]
    print("\nDEEPEST DRAWDOWN  (needs resupply to stay usable)")
    print(f"  {'station':32s} {'low':>7s} {'at':>6s} {'cap':>5s} {'% of cap':>9s}")
    for sid in drained:
        b, v = trough(sid)
        cap = stations[sid]["capacity"] or 1
        print(f"  {stations[sid]['name'][:32]:32s} {v:+7.1f} {b//60:3d}:{b%60:02d} "
              f"{cap:5d} {100*abs(v)/cap:8.0f}%")

    filled = sorted(stations, key=lambda s: -crest(s)[1])[:8]
    print("\nDEEPEST PILE-UP  (dock hunt likely)")
    print(f"  {'station':32s} {'high':>7s} {'at':>6s} {'cap':>5s} {'% of cap':>9s}")
    for sid in filled:
        b, v = crest(sid)
        cap = stations[sid]["capacity"] or 1
        print(f"  {stations[sid]['name'][:32]:32s} {v:+7.1f} {b//60:3d}:{b%60:02d} "
              f"{cap:5d} {100*abs(v)/cap:8.0f}%")

    payload["curves_fri"] = {s: [round(v, 1) for _, v in curves[s]] for s in curves}
    payload["hourly"] = {f"{d}": [round(hourly[(d, h)][0] / (n_days.get(d, 1) or 1), 1)
                                  for h in range(24)] for d in TARGET_DOWS}
    payload["hourly_esh"] = {f"{d}": [round(hourly[(d, h)][1] / max(hourly[(d, h)][0], 1), 3)
                                      for h in range(24)] for d in TARGET_DOWS}
    payload["capacity"] = {s: stations[s]["capacity"] for s in stations}
    payload["names"] = {s: stations[s]["name"] for s in stations}
    payload["zones"] = {s: stations[s]["zone"] for s in stations}
    payload["curve_start_min"] = 300
    payload["curve_bin"] = BIN
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    print("\n" + "=" * 62)
    print("BUSIEST STATION PAIRS")
    print("=" * 62)
    for (a, b), c in sorted(pairs.items(), key=lambda x: -x[1])[:10]:
        print(f"  {c:7,}  {stations[a]['name'][:28]:28s} -> {stations[b]['name'][:28]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
