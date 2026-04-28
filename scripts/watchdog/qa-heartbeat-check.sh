#!/usr/bin/env bash
# QA Fleet heartbeat watchdog — cross-platform (macOS + Linux).
#
# Each routine writes its UTC timestamp to fleet-workspace/heartbeats/<n>.txt
# on every run. This script checks each heartbeat is fresh; if stale or
# missing it fires an OS notification (macOS) or sends mail (Linux) and
# writes to a log file.
#
# === macOS (launchd, every 15 min) ===
# See com.sashi.qafleet.watchdog.plist next to this file.
# Manual test: bash scripts/watchdog/qa-heartbeat-check.sh
#
# === Linux homelab (cron, every 15 min) ===
# Install to /usr/local/bin/qa-heartbeat-check.sh, then:
#
#   # /etc/cron.d/qa-fleet-watchdog
#   */15 * * * * sashi FLEET_DIR=/path/to/always-on-engineering-fleet ALERT_EMAIL=you@example.com /usr/local/bin/qa-heartbeat-check.sh
#
# Environment variables:
#   FLEET_DIR          path to the cloned fleet repo (default: ~/Documents/projects/...)
#   SLACK_WEBHOOK_URL  optional Slack webhook for alert notifications
#   ALERT_EMAIL        optional email address for mail(1) alerts (Linux fallback)

set -euo pipefail

FLEET_DIR="${FLEET_DIR:-/Users/Sashi/Documents/projects/always-on-engineering-fleet}"
HEARTBEAT_DIR="$FLEET_DIR/fleet-workspace/heartbeats"
LOG_FILE="$FLEET_DIR/fleet-workspace/watchdog.log"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
ALERT_EMAIL="${ALERT_EMAIL:-}"

mkdir -p "$HEARTBEAT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

file_mtime() {
  local file="$1"
  if [[ "$(uname)" == "Darwin" ]]; then
    stat -f %m "$file"
  else
    stat -c %Y "$file"
  fi
}

notify_os() {
  local title="$1" message="$2"
  if [[ "$(uname)" == "Darwin" ]]; then
    osascript -e "display notification \"$message\" with title \"$title\" sound name \"Basso\"" 2>/dev/null || true
  elif [[ -n "${ALERT_EMAIL:-}" ]]; then
    echo "$message" | mail -s "$title" "$ALERT_EMAIL" 2>/dev/null || true
  fi
}

notify_slack() {
  [[ -z "$SLACK_WEBHOOK_URL" ]] && return 0
  local message="$1"
  curl -sS -X POST -H "Content-Type: application/json" \
    --data "{\"text\":\"$message\"}" \
    "$SLACK_WEBHOOK_URL" >/dev/null || true
}

log() {
  echo "$(now_iso) $1" | tee -a "$LOG_FILE"
}

check_age() {
  local name="$1" file="$2" max_age_sec="$3"

  if [[ ! -f "$file" ]]; then
    msg="MISSING heartbeat: $name — file not found at $file"
    log "$msg"
    notify_os "QA Fleet alert: $name" "$msg"
    notify_slack "$msg"
    return
  fi

  local mtime now age_sec
  mtime=$(file_mtime "$file")
  now=$(date +%s)
  age_sec=$(( now - mtime ))

  if (( age_sec > max_age_sec )); then
    msg="STALE heartbeat: $name — last beat ${age_sec}s ago (max ${max_age_sec}s)"
    log "$msg"
    notify_os "QA Fleet alert: $name" "$msg"
    notify_slack "$msg"
  else
    log "OK $name (age=${age_sec}s)"
  fi
}

# Thresholds (seconds). Each is ~2x the routine's expected fire interval.
check_age "qa-smoke-hourly"  "$HEARTBEAT_DIR/qa-smoke-hourly.txt"  7200    # 2h
check_age "qa-signup-daily"  "$HEARTBEAT_DIR/qa-signup-daily.txt"  129600  # 36h
check_age "qa-explore-daily" "$HEARTBEAT_DIR/qa-explore-daily.txt" 129600  # 36h
