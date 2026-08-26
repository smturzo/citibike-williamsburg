#!/usr/bin/env bash
# Wipe the staging branch back to one empty commit. Run only AFTER compaction has
# been committed to main, or staged data is lost.
set -euo pipefail
REMOTE="${1:-origin}"; BRANCH="${2:-data-staging}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 "$(git remote get-url "$REMOTE")" "$TMP/s" -q
cd "$TMP/s"
git checkout --orphan fresh -q
git rm -rf . -q >/dev/null 2>&1 || true
git config user.name "citibike-collector"; git config user.email "actions@github.com"
echo "Transient shard staging. Reset after each compaction. Do not merge." > README.md
git add README.md && git commit -q -m "reset staging $(date -u +%Y-%m-%d)"
git push -q --force origin "HEAD:$BRANCH"
echo "staging branch reset"
