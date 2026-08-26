#!/usr/bin/env python3
"""Fetch hourly weather for the tracked area into data/weather/YYYY-MM.csv.

Deliberately backfill-based rather than logged live. Open-Meteo will serve up to
92 days of past hourly actuals, so one daily run repairs any gap a dead collector
left behind - weather is the one input we can always recover after the fact.

Usage: python3 collect/weather.py [--days 7]
"""
import argparse, csv, json, os, sys, urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Centroid of the tracked area. It spans ~6km; hourly weather does not vary
# meaningfully across that, so one point is enough.
LAT, LON = 40.7160, -73.9520
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&hourly=temperature_2m,apparent_temperature,precipitation,rain,snowfall,"
       "wind_speed_10m,wind_gusts_10m,relative_humidity_2m,cloud_cover,weather_code"
       "&temperature_unit=fahrenheit&timezone=America%2FNew_York"
       "&past_days={days}&forecast_days=1")

FIELDS = ["hour_local", "temp_f", "apparent_f", "precip_mm", "rain_mm", "snow_cm",
          "wind_kmh", "gust_kmh", "humidity", "cloud_pct", "weather_code"]
KEYS = ["temperature_2m", "apparent_temperature", "precipitation", "rain", "snowfall",
        "wind_speed_10m", "wind_gusts_10m", "relative_humidity_2m", "cloud_cover", "weather_code"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="days of history to (re)fetch, max 92")
    args = ap.parse_args()
    days = max(1, min(args.days, 92))

    req = urllib.request.Request(URL.format(lat=LAT, lon=LON, days=days),
                                 headers={"User-Agent": "williamsburg-citibike/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = json.load(r)["hourly"]

    by_month = defaultdict(dict)
    for i, t in enumerate(h["time"]):
        row = {"hour_local": t}
        for f, k in zip(FIELDS[1:], KEYS):
            v = h[k][i]
            row[f] = "" if v is None else v
        by_month[t[:7]][t] = row

    total = 0
    for month, rows in sorted(by_month.items()):
        path = os.path.join(ROOT, "data", "weather", f"{month}.csv")
        merged = {}
        if os.path.exists(path):
            with open(path) as f:
                for r0 in csv.DictReader(f):
                    merged[r0["hour_local"]] = r0
        # Fresh values win: a forecast hour fetched yesterday is superseded by the
        # actual observation for that same hour today.
        merged.update(rows)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for k in sorted(merged):
                w.writerow(merged[k])
        total += len(merged)
        print(f"{month}: {len(merged)} hours ({len(rows)} refreshed)")
    print(f"total {total} hours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
