#!/usr/bin/env python3
"""Append-only registry mapping GBFS station_id -> a small integer key.

The snapshots table stores `sid` instead of the 19-character GBFS station_id.
Repeated 20M times a year, that text is most of the database.

The mapping must be *stable*: the DB gets rebuilt from CSVs regularly, and if
keys were derived from sort order, adding one station would silently renumber
every row. So keys are assigned once, appended, and never reused.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "config", "station_keys.json")


def load():
    if os.path.exists(PATH):
        return {k: int(v) for k, v in json.load(open(PATH)).items()}
    return {}


def sync(station_ids):
    """Ensure every station_id has a key. Returns the full mapping."""
    keys = load()
    nxt = max(keys.values(), default=0) + 1
    added = 0
    for s in sorted(station_ids):
        if s not in keys:
            keys[s] = nxt
            nxt += 1
            added += 1
    if added or not os.path.exists(PATH):
        with open(PATH, "w") as f:
            json.dump({k: keys[k] for k in sorted(keys, key=lambda x: keys[x])}, f, indent=0)
    return keys, added


if __name__ == "__main__":
    st = json.load(open(os.path.join(ROOT, "config", "stations.json")))["stations"]
    keys, added = sync([s["station_id"] for s in st])
    print(f"{len(keys)} keys registered ({added} new) -> {PATH}")
