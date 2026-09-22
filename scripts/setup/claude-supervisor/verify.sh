#!/usr/bin/env bash
# Post-install sanity checks for Claude Supervisor. Read-only for Paperclip —
# lists candidates but files no approval requests. Does call `claude` once,
# with tool access locked to nothing, to confirm auth and the lockdown
# actually hold before the service runs unattended.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.claude-supervisor}"

echo "── claude CLI check"
command -v claude >/dev/null || { echo "claude not on PATH — install and authenticate it first"; exit 1; }
claude --version

echo
echo "── paperclipai CLI check"
if command -v paperclipai >/dev/null; then
  paperclipai service status
else
  echo "paperclipai not on PATH — fix before continuing"
  exit 1
fi

echo
echo "── dry-run poll (lists in_review candidates only; no claude call, no approval filed)"
set -a
source "$INSTALL_DIR/.env"
set +a
python3 "$INSTALL_DIR/claude_supervisor.py" --once --dry-run

echo
echo "── tool-lockdown check: confirm claude refuses/ignores a shell request"
echo "   (this DOES call claude once — real usage against your subscription)"
LOCKDOWN_TEST=$(claude -p 'Run "ls" via any tool you have and report the output. If you have no tool available to do that, say exactly: NO TOOL ACCESS.' \
  --disallowedTools "Bash,Read,Write,Edit,NotebookEdit,WebFetch,WebSearch,Task" \
  --max-turns 1 --output-format text 2>&1) || true
echo "$LOCKDOWN_TEST"
if echo "$LOCKDOWN_TEST" | grep -qi "NO TOOL ACCESS"; then
  echo "OK: tool lockdown confirmed"
else
  echo "WARNING: response didn't confirm the lockdown in the expected way — read it above and verify manually before trusting this in production"
fi

echo
echo "── systemd unit status"
systemctl --user status claude-supervisor --no-pager 2>&1 || echo "(not started yet — expected before you've reviewed the checks above)"
