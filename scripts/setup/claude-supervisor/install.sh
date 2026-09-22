#!/usr/bin/env bash
# Install/update the Claude Supervisor daemon as a systemd --user service.
#
# Run this ON the host that runs Paperclip/Hermes (per OPERATIONS.md, that's
# the Ubuntu box, as user `sashi`) — NOT from a Mac Claude Code session,
# which has no access to that host. Copy this directory over first, e.g.:
#   scp -r scripts/setup/claude-supervisor sashi@sashi-llm:~/claude-supervisor-setup
#   ssh sashi@sashi-llm
#   cd ~/claude-supervisor-setup && ./install.sh
#
# Before running this, by hand (see README.md "Manual setup" — this script
# does NOT do these; they need board-level Paperclip access):
#   1. Confirm `paperclipai` CLI is installed and authenticated
#      (`paperclipai service status`).
#   2. Create a Paperclip agent identity for claude-supervisor and a scoped
#      API key for it.
#   3. Obtain an Anthropic API key.
#
# This script IS idempotent — re-running it updates the venv/files/service
# in place without duplicating anything, and never overwrites an existing
# .env.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.claude-supervisor}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
say()  { echo -e "${BLUE}── $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
fail() { echo -e "${RED}✗ $*${NC}"; }

command -v python3 >/dev/null || { fail "python3 not found"; exit 1; }
command -v paperclipai >/dev/null || warn "paperclipai CLI not found on PATH — the daemon will fail until it is"

say "Installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/claude_supervisor.py" "$INSTALL_DIR/claude_supervisor.py"
ok "copied claude_supervisor.py"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$SCRIPT_DIR/claude-supervisor.env.example" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  warn "wrote a template .env at $INSTALL_DIR/.env — edit it with real values before starting the service"
else
  ok ".env already exists — leaving it as-is"
fi
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
  say "creating venv"
  python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet anthropic
ok "venv ready with anthropic SDK installed"

mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/claude-supervisor.service" "$SYSTEMD_USER_DIR/claude-supervisor.service"
systemctl --user daemon-reload
ok "systemd --user unit installed"

if ! loginctl show-user "$(whoami)" 2>/dev/null | grep -q "Linger=yes"; then
  warn "linger is not enabled for $(whoami) — the service would stop when you log out."
  echo "  Other fleet services rely on linger (per OPERATIONS.md). Enable it with:"
  echo "    sudo loginctl enable-linger $(whoami)"
fi

echo
warn "Not starting the service automatically."
echo "Next steps:"
echo "  1. Edit $INSTALL_DIR/.env with real ANTHROPIC_API_KEY, PAPERCLIP_API_KEY, CLAUDE_SUPERVISOR_AGENT_ID"
echo "  2. Run ./verify.sh — dry-runs a single pass, calls nothing external except paperclipai read calls"
echo "  3. When that looks right: systemctl --user enable --now claude-supervisor"
echo "  4. Watch it:            journalctl --user -u claude-supervisor -f"
