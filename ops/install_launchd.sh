#!/bin/zsh
# Installs the two launchd agents. Run this yourself when you're ready.
set -e
mkdir -p ~/Library/LaunchAgents
cp "/Users/bargeen/Desktop/CitiBike/ops/com.citibike.collect.plist" ~/Library/LaunchAgents/
cp "/Users/bargeen/Desktop/CitiBike/ops/com.citibike.daily.plist"   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.citibike.collect.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.citibike.daily.plist   2>/dev/null || true
launchctl load  ~/Library/LaunchAgents/com.citibike.collect.plist
launchctl load  ~/Library/LaunchAgents/com.citibike.daily.plist
echo "installed. verify with: launchctl list | grep citibike"
