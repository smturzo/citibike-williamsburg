#!/usr/bin/env bash
# Download and extract one or more months of trip archive.
#   analysis/fetch_trips.sh 202607 202606 202605
# Each ~1GB zip is downloaded, filtered to the tracked stations, then deleted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
mkdir -p data/trips/raw
for M in "$@"; do
  OUT="data/trips/filtered/${M}.csv.gz"
  if [ -f "$OUT" ]; then echo "$M already extracted, skipping"; continue; fi
  echo "=== $M ==="
  curl -sS --fail --max-time 3600 -o "data/trips/raw/${M}.zip" \
    "https://s3.amazonaws.com/tripdata/${M}-citibike-tripdata.zip"
  python3 analysis/extract_trips.py "data/trips/raw/${M}.zip"
done
python3 ops/sizecheck.py
