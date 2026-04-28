#!/usr/bin/env bash
# QA Fleet heartbeat watchdog — Mac-friendly.
#
# Each routine writes its UTC timestamp to fleet-workspace/heartbeats/<n>.txt
# on every run. This script checks each heartbeat is fresh; if not, it surfaces
# a macOS notification AND writes to a log file Sashi reviews.
#
# Install: launchd is more reliable than cron on modern macOS. See
# com.sashi.qafleet.watchdog.plist next to this file.
#
# Manual run (for testing): /usr/local/bin/qa-heartbeat-check.sh

set -euo pipefail

FLEET_DIR="${FLEET_DIR:-/Users/Sashi/Documents/projects/always-on-engineering-fleet}"
HEARTBEAT_DIR="$FLEET_DIR/fleet-workspace/heartbeats"
LOG_FILE="$FLEET_DIR/fleet-workspace/watchdog.log"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"       # optional — leave blank to skip
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"   # optional — Telegram bot token
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"       # optional — Telegram chat/user ID

mkdir -p "$HEARTBEAT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

notify_mac() {
  [[ "$(uname)" != "Darwin" ]] && return 0
  local title="$1" subtitle="$2" message="$3"
  osascript -e "display notification \"$message\" with title \"$title\" subtitle \"$subtitle\" sound name \"Basso\"" 2>/dev/null || true
}

notify_slack() {
  [[ -z "$SLACK_WEBHOOK_URL" ]] && return 0
  local message="$1"
  curl -sS -X POST -H "Content-Type: application/json" \
    --data "{\"text\":\"$message\"}" \
    "$SLACK_WEBHOOK_URL" >/dev/null || true
}

notify_telegram() {
  [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]] && return 0
  local message="$1"
  curl -sS -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    --data "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"🚨 QA Fleet\n${message}\",\"parse_mode\":\"HTML\"}" \
    >/dev/null || true
}

log() {
  echo "$(now_iso) $1" | tee -a "$LOG_FILE"
}

check_age() {
  local name="$1" file="$2" max_age_sec="$3"

  if [[ ! -f "$file" ]]; then
    msg="MISSING heartbeat: $name — file not found at $file"
    log "$msg"
    notify_mac "QA Fleet alert" "$name has never run" "$msg"
    notify_slack "$msg"
    notify_telegram "$msg"
    return
  fi

  local mtime now age_sec
  if [[ "$(uname)" == "Darwin" ]]; then
    mtime=$(stat -f %m "$file")
  else
    mtime=$(stat -c %Y "$file")
  fi
  now=$(date +%s)
  age_sec=$(( now - mtime ))

  if (( age_sec > max_age_sec )); then
    msg="STALE heartbeat: $name — last beat ${age_sec}s ago (max ${max_age_sec}s)"
    log "$msg"
    notify_mac "QA Fleet alert" "$name is silent" "$msg"
    notify_slack "$msg"
    notify_telegram "$msg"
  else
    log "OK $name (age=${age_sec}s)"
  fi
}

# Thresholds (seconds). Set to ~2× the routine's expected interval.
check_age "qa-smoke-90min"   "$HEARTBEAT_DIR/qa-smoke-90min.txt"   10800   # 3h (2× the 90-min interval)
check_age "qa-signup-daily"  "$HEARTBEAT_DIR/qa-signup-daily.txt"  129600  # 36h
check_age "qa-explore-daily" "$HEARTBEAT_DIR/qa-explore-daily.txt" 129600  # 36h
