#!/usr/bin/env bash
# Post-install sanity checks for Pipeline Advancer. Dry-run only — lists what
# it would do but calls no paperclipai write endpoint and posts no Slack
# message.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.pipeline-advancer}"

echo "── paperclipai CLI check"
if command -v paperclipai >/dev/null; then
  paperclipai service status
else
  echo "paperclipai not on PATH — fix before continuing"
  exit 1
fi

echo
echo "── .env sanity check (presence only, never prints values)"
for var in PAPERCLIP_COMPANY_ID PAPERCLIP_BOARD_KEY_WORKAROUND SLACK_BOT_TOKEN PIPELINE_SLACK_USER_ID; do
  if grep -q "^${var}=.\+" "$INSTALL_DIR/.env" 2>/dev/null; then
    echo "  ✓ $var is set"
  else
    echo "  ✗ $var is missing or empty in $INSTALL_DIR/.env"
  fi
done

echo
echo "── dry-run poll (lists pipeline-enrolled candidates and what would happen; no writes, no Slack)"
set -a
source "$INSTALL_DIR/.env"
set +a
python3 "$INSTALL_DIR/pipeline_advancer.py" --once --dry-run

echo
echo "── systemd unit status"
systemctl --user status pipeline-advancer.timer --no-pager 2>&1 || echo "(not started yet — expected before you've reviewed the checks above)"
