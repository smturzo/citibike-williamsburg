#!/usr/bin/env bash
# Wipe the staging branch back to a single empty commit.
#
# Run ONLY after compaction is committed to main, or staged data is lost.
#
# Pure plumbing: commit the empty tree and force-push it. No clone, so it uses the
# current checkout's authenticated remote - the previous clone-based version would
# have failed its force-push in Actions for the same reason push_shards.sh did.
set -euo pipefail
REMOTE="${1:-origin}"
BRANCH="${2:-data-staging}"

EMPTY_TREE="$(git hash-object -w -t tree /dev/null)"
COMMIT="$(git -c user.name=citibike-collector -c user.email=actions@github.com \
          commit-tree "$EMPTY_TREE" -m "reset $BRANCH $(date -u +%Y-%m-%d)")"
git push -q --force "$REMOTE" "$COMMIT:refs/heads/$BRANCH"
echo "staging branch reset to an empty commit"
