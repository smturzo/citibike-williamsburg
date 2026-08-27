#!/usr/bin/env bash
# Install the two launchd agents.
#
# The plists are generated here rather than committed: they embed absolute paths
# for this machine (repo location, python interpreter), which are neither portable
# nor something to publish in a public repo.
#
# Both agents invoke python3 directly. Do NOT switch them to a shell wrapper -
# launchd runs agents in a restricted context where /bin/zsh was denied read
# access to this directory ("can't open input file") while the Python framework
# binary works. That failure does not reproduce from an interactive shell.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"

gen() {  # gen <label> <script> <schedule-xml> <runatload>
  cat > "$ROOT/ops/com.citibike.$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.citibike.$1</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$ROOT/$2</string>
$4
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
$3
  <key>StandardOutPath</key><string>$ROOT/data/$1.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/$1.err</string>
</dict>
</plist>
PLIST
}

gen collect collect/collect.py \
  '  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>' \
  '    <string>--src</string><string>mac</string>'

gen daily ops/daily.py \
  '  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>10</integer></dict>
  <key>RunAtLoad</key><false/>' \
  ''

for L in collect daily; do
  cp "$ROOT/ops/com.citibike.$L.plist" "$AGENTS/"
  launchctl unload "$AGENTS/com.citibike.$L.plist" 2>/dev/null || true
  launchctl load  "$AGENTS/com.citibike.$L.plist"
done
echo "installed. verify with: launchctl list | grep citibike"
