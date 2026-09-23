#!/usr/bin/env bash
# Install/update the Pipeline Advancer daemon as a systemd --user service.
# Same shape as ../claude-supervisor/install.sh — read that one's comments
# too if anything here is unclear, this is a direct sibling.
#
# Before running this, by hand (needs board-level Paperclip access):
#   1. Confirm `paperclipai` CLI is installed and authenticated
#      (`paperclipai service status`).
#   2. Create a Paperclip agent identity for pipeline-advancer — see
#      README.md "Manual setup". You need its agent id for step 3 below.
#   3. Substitute that agent id into pipeline-advancer.service in place of
#      __PIPELINE_ADVANCER_AGENT_ID__ (this script does that for you if you
#      pass it as $1).
#
# This script IS idempotent — re-running it updates the files/service in
# place without duplicating anything, and never overwrites an existing .env.

set -euo pipefail

AGENT_ID="${1:-}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.pipeline-advancer}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
say()  { echo -e "${BLUE}── $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
fail() { echo -e "${RED}✗ $*${NC}"; }

command -v python3 >/dev/null || { fail "python3 not found"; exit 1; }
command -v paperclipai >/dev/null || warn "paperclipai CLI not found on PATH — the daemon will fail until it is"

if [[ -z "$AGENT_ID" ]]; then
  warn "No agent id passed as \$1 — pipeline-advancer.service will be installed with the"
  warn "__PIPELINE_ADVANCER_AGENT_ID__ placeholder still in it. Edit"
  warn "$SYSTEMD_USER_DIR/pipeline-advancer.service by hand before enabling the timer."
fi

say "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/pipeline_advancer.py" "$INSTALL_DIR/pipeline_advancer.py"
ok "copied pipeline_advancer.py"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$SCRIPT_DIR/pipeline-advancer.env.example" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  warn "wrote a template .env at $INSTALL_DIR/.env — edit it with real values before starting the service"
else
  ok ".env already exists — leaving it as-is"
fi
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true

mkdir -p "$SYSTEMD_USER_DIR"
if [[ -n "$AGENT_ID" ]]; then
  sed "s/__PIPELINE_ADVANCER_AGENT_ID__/$AGENT_ID/" "$SCRIPT_DIR/pipeline-advancer.service" \
    > "$SYSTEMD_USER_DIR/pipeline-advancer.service"
  ok "wrote pipeline-advancer.service with agent id $AGENT_ID"
else
  cp "$SCRIPT_DIR/pipeline-advancer.service" "$SYSTEMD_USER_DIR/pipeline-advancer.service"
fi
cp "$SCRIPT_DIR/pipeline-advancer.timer" "$SYSTEMD_USER_DIR/pipeline-advancer.timer"
systemctl --user daemon-reload
ok "systemd --user units installed"

if ! loginctl show-user "$(whoami)" 2>/dev/null | grep -q "Linger=yes"; then
  warn "linger is not enabled for $(whoami) — the service would stop when you log out."
  echo "    sudo loginctl enable-linger $(whoami)"
fi

echo
warn "Not starting the service automatically."
echo "Next steps:"
echo "  1. Edit $INSTALL_DIR/.env with real values (see README.md)"
echo "  2. Confirm $SYSTEMD_USER_DIR/pipeline-advancer.service has a real agent id, not the placeholder"
echo "  3. Run ./verify.sh — dry-runs a single pass, no Paperclip writes, no Slack posts"
echo "  4. When that looks right: systemctl --user enable --now pipeline-advancer.timer"
echo "  5. Watch it:            journalctl --user -u pipeline-advancer -f"
