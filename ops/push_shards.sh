#!/usr/bin/env bash
# Push freshly-written shards to the `data-staging` branch.
#
# Shards must never land in main's history: git keeps every blob it ever saw, so
# committing 288 small CSVs a day would cost ~464MB/year in main even though
# compaction deletes them from the working tree the next morning. Staging them on
# a throwaway branch means main's history only ever receives the compacted
# .csv.gz files (~137MB/year), and the staging branch is reset to a fresh orphan
# commit after each compaction so its own history never accumulates either.
#
# Usage: ops/push_shards.sh <remote> <branch>
set -euo pipefail
REMOTE="${1:-origin}"
BRANCH="${2:-data-staging}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

shopt -s nullglob
SHARDS=(data/raw/*/*.csv)
if [ ${#SHARDS[@]} -eq 0 ]; then echo "no shards to push"; exit 0; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  git clone --depth 1 --branch "$BRANCH" --single-branch \
      "$(git remote get-url "$REMOTE")" "$TMP/s" -q
else
  echo "creating $BRANCH"
  git clone --depth 1 "$(git remote get-url "$REMOTE")" "$TMP/s" -q
  git -C "$TMP/s" checkout --orphan "$BRANCH" -q
  git -C "$TMP/s" rm -rf . -q >/dev/null 2>&1 || true
fi

mkdir -p "$TMP/s/shards"
for f in "${SHARDS[@]}"; do
  day="$(basename "$(dirname "$f")")"
  mkdir -p "$TMP/s/shards/$day"
  cp "$f" "$TMP/s/shards/$day/"
done

cd "$TMP/s"
git config user.name  "citibike-collector"
git config user.email "actions@github.com"
git add -A
if git diff --cached --quiet; then echo "nothing new"; exit 0; fi
git commit -q -m "shards: $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3 4 5; do
  if git push -q origin "HEAD:$BRANCH" 2>/dev/null; then echo "pushed ${#SHARDS[@]} shard(s)"; exit 0; fi
  git pull --rebase -q origin "$BRANCH" || true
  sleep $((RANDOM % 6 + 2))
done
echo "push failed after retries" >&2; exit 1
