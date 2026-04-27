#!/usr/bin/env bash
# Homelab watchdog — copy to /usr/local/bin/qa-heartbeat-check.sh
# Add to /etc/cron.d/qa-fleet-watchdog:
#   */15 * * * * sashi /usr/local/bin/qa-heartbeat-check.sh
set -euo pipefail

FLEET_DIR=/Users/Sashi/Documents/projects/always-on-engineering-fleet/fleet-workspace/heartbeats

check_age() {
  local file="$1" max_age_sec="$2" name="$3"
  if [[ ! -f "$file" ]]; then
    echo "MISSING: $name has never heartbeated" | mail -s "QA fleet down: $name" you@example.com
    return
  fi
  local age_sec=$(( $(date +%s) - $(stat -f %m "$file") ))
  if (( age_sec > max_age_sec )); then
    echo "STALE: $name last beat ${age_sec}s ago (max ${max_age_sec})" \
      | mail -s "QA fleet silent: $name" you@example.com
  fi
}

check_age "$FLEET_DIR/qa-smoke-hourly.txt"  7200   "Hourly smoke"      # 2h
check_age "$FLEET_DIR/qa-signup-daily.txt"  129600 "Daily signup"      # 36h
check_age "$FLEET_DIR/qa-explore-daily.txt" 129600 "Daily exploration" # 36h
