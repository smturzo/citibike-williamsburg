#!/usr/bin/env python3
"""Resolve the tracked station set from GBFS station_information + config/zones.json.

Writes config/stations.json (committed, so the collector never depends on a live
lookup) and docs/data/stations.json (served to the dashboard).

Re-run this when Citi Bike adds or moves stations in the tracked area.
"""
import json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO_URL = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_information.json"


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "williamsburg-citibike/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def zone_of(lat, lon, zones):
    for name, b in zones.items():
        if b["lat_min"] <= lat < b["lat_max"] and b["lon_min"] <= lon < b["lon_max"]:
            return name
    return None


def main():
    zones = json.load(open(os.path.join(ROOT, "config", "zones.json")))["zones"]
    data = fetch(INFO_URL)

    out = []
    for s in data["data"]["stations"]:
        z = zone_of(s["lat"], s["lon"], zones)
        if not z:
            continue
        out.append({
            "station_id": str(s["station_id"]),
            "name": s["name"],
            "short_name": s.get("short_name"),
            "lat": round(s["lat"], 6),
            "lon": round(s["lon"], 6),
            "capacity": s.get("capacity", 0),
            "zone": z,
        })
    out.sort(key=lambda x: (x["zone"], x["name"]))

    payload = {"generated_at": data.get("last_updated"), "count": len(out), "stations": out}
    for path in (os.path.join(ROOT, "config", "stations.json"),
                 os.path.join(ROOT, "docs", "data", "stations.json")):
        with open(path, "w") as f:
            json.dump(payload, f, indent=1)

    by_zone = {}
    for s in out:
        z = by_zone.setdefault(s["zone"], [0, 0])
        z[0] += 1
        z[1] += s["capacity"]
    for z, (n, cap) in sorted(by_zone.items()):
        print(f"{z:20s} {n:4d} stations  {cap:5d} docks")
    print(f"{'TOTAL':20s} {len(out):4d} stations  {sum(s['capacity'] for s in out):5d} docks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
