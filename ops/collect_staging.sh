#!/usr/bin/env bash
# Pull every staged shard into data/raw/ so compaction can fold them in.
#
# Reads via fetch + git-archive off the current checkout rather than a fresh
# clone - same reason as push_shards.sh: a separate clone does not inherit the
# credentials actions/checkout injects. Reading a public repo would survive that,
# but keeping one mechanism across all three staging scripts means there is only
# one thing to get right.
set -euo pipefail
REMOTE="${1:-origin}"
BRANCH="${2:-data-staging}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  echo "no $BRANCH branch yet - nothing staged"; exit 0
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git fetch -q --no-tags --depth 1 "$REMOTE" "$BRANCH"
git archive FETCH_HEAD | tar -x -C "$TMP"

if [ -d "$TMP/shards" ]; then
  mkdir -p data/raw
  cp -R "$TMP/shards/." data/raw/
  echo "pulled $(find "$TMP/shards" -name '*.csv' | wc -l | tr -d ' ') staged shard(s)"
else
  echo "staging branch is empty"
fi
