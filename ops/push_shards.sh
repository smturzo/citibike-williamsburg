#!/usr/bin/env bash
# Push freshly-written shards to the `data-staging` branch.
#
# Shards must never land in main's history: git keeps every blob it ever saw, so
# committing shards to main would cost ~460MB/year even though compaction deletes
# them the next morning. Staging them on a throwaway branch means main only ever
# receives the compacted .csv.gz, and staging is reset after each compaction.
#
# Uses `git worktree` off the CURRENT checkout rather than a fresh clone. This is
# load-bearing: actions/checkout injects credentials into the checked-out repo's
# local git config, and a separate `git clone` does not inherit them - which made
# every cloud run fail with "push failed after retries" while the same script
# worked locally over SSH. A worktree shares the parent's config, so one code path
# authenticates in both places. It also avoids re-cloning the whole repo per run.
#
# Usage: ops/push_shards.sh [remote] [branch]
set -euo pipefail
REMOTE="${1:-origin}"
BRANCH="${2:-data-staging}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

shopt -s nullglob
SHARDS=(data/raw/*/*.csv)
if [ ${#SHARDS[@]} -eq 0 ]; then echo "no shards to push"; exit 0; fi

GIT_ID=(-c user.name=citibike-collector -c user.email=actions@github.com)

# Create the branch if it is missing, using plumbing - an empty tree committed
# directly, so no working copy is needed just to make an orphan root.
if ! git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
  echo "creating $BRANCH"
  EMPTY_TREE="$(git hash-object -w -t tree /dev/null)"
  ROOT_COMMIT="$(git "${GIT_ID[@]}" commit-tree "$EMPTY_TREE" -m "init $BRANCH")"
  git push -q "$REMOTE" "$ROOT_COMMIT:refs/heads/$BRANCH"
fi

BASE="$(mktemp -d)"; WT="$BASE/wt"
cleanup() { git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$BASE"; }
trap cleanup EXIT

for attempt in 1 2 3 4 5; do
  # Re-fetch every attempt: on a losing race the tip has moved, and rebuilding on
  # the new tip is simpler and safer than rebasing a commit of added files.
  git fetch -q --no-tags --depth 1 "$REMOTE" "$BRANCH"
  git worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT"
  git worktree add -q --detach "$WT" FETCH_HEAD

  for f in "${SHARDS[@]}"; do
    day="$(basename "$(dirname "$f")")"
    mkdir -p "$WT/shards/$day"
    cp "$f" "$WT/shards/$day/"
  done

  git -C "$WT" add -A
  if git -C "$WT" diff --cached --quiet; then echo "nothing new"; exit 0; fi
  git -C "$WT" "${GIT_ID[@]}" commit -q -m "shards: $(date -u +%Y-%m-%dT%H:%MZ)"

  if git -C "$WT" push -q "$REMOTE" "HEAD:refs/heads/$BRANCH" 2>/dev/null; then
    echo "pushed ${#SHARDS[@]} shard(s) to $BRANCH"
    exit 0
  fi
  echo "push attempt $attempt lost a race; retrying" >&2
  sleep $((RANDOM % 6 + 2))
done

echo "push failed after retries" >&2
exit 1
