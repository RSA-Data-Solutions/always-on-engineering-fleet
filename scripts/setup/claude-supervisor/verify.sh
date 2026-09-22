#!/usr/bin/env bash
# Post-install sanity checks for Claude Supervisor. Read-only — makes no
# changes, files no approval requests, calls the Anthropic API zero times.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.claude-supervisor}"

echo "── venv + SDK import check"
"$INSTALL_DIR/venv/bin/python3" -c "import anthropic; print('anthropic SDK OK:', anthropic.__version__)"

echo
echo "── paperclipai CLI check"
if command -v paperclipai >/dev/null; then
  paperclipai service status
else
  echo "paperclipai not on PATH — fix before continuing"
  exit 1
fi

echo
echo "── dry-run poll (lists in_review candidates only; no Claude call, no approval filed)"
set -a
source "$INSTALL_DIR/.env"
set +a
"$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/claude_supervisor.py" --once --dry-run

echo
echo "── systemd unit status"
systemctl --user status claude-supervisor --no-pager 2>&1 || echo "(not started yet — expected before you've reviewed the dry run above)"
