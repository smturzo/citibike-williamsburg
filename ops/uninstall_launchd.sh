#!/bin/zsh
launchctl unload ~/Library/LaunchAgents/com.citibike.collect.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.citibike.daily.plist   2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.citibike.collect.plist ~/Library/LaunchAgents/com.citibike.daily.plist
echo "removed."
