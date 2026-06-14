#!/usr/bin/env bash
# Cleanly restart Lifeboard via launchd (com.lifeboard.app).
# launchd's KeepAlive owns the process — kickstart -k stops the current
# instance and starts a fresh one, with no duplicates.
# Usage: ./restart.sh

set -e

label="com.lifeboard.app"
uid="$(id -u)"

if ! launchctl print "gui/$uid/$label" >/dev/null 2>&1; then
  echo "launchd agent $label not loaded. Load it with:"
  echo "  launchctl bootstrap gui/$uid ~/Library/LaunchAgents/$label.plist"
  exit 1
fi

launchctl kickstart -k "gui/$uid/$label"
sleep 1
running=$(pgrep -f "[Pp]ython.* run\.py$|/lifeboard/run\.py" | wc -l | tr -d ' ')
echo "Lifeboard restarted via launchd. Active instances: $running. Logs: ~/.lifeboard/stdout.log"
