#!/usr/bin/env bash
# Pull every staged shard into data/raw/, then reset the staging branch to a
# fresh orphan commit so its history never accumulates.
set -euo pipefail
REMOTE="${1:-origin}"
BRANCH="${2:-data-staging}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  echo "no $BRANCH branch yet - nothing staged"; exit 0
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 --branch "$BRANCH" --single-branch \
    "$(git remote get-url "$REMOTE")" "$TMP/s" -q

if [ -d "$TMP/s/shards" ]; then
  mkdir -p data/raw
  cp -R "$TMP/s/shards/." data/raw/
  echo "pulled $(find "$TMP/s/shards" -name '*.csv' | wc -l | tr -d ' ') staged shard(s)"
fi
echo "$TMP/s" > /tmp/citibike_staging_path
