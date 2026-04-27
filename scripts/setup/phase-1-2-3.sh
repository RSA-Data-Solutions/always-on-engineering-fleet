#!/usr/bin/env bash
# Phases 1, 2, and 3 setup — one script, with confirmations.
#
# Run from your Mac. Set TARGET_URL below to wherever your orchestrator
# runs (localhost or homelab). The script edits files on your Mac, calls
# the orchestrator URL for verification, and pushes to GitHub.
#
# Usage:
#   ./phase-1-2-3.sh                   # interactive — recommended
#   ./phase-1-2-3.sh --skip-phase-1    # skip if already done
#   ./phase-1-2-3.sh --dry-run         # show what would happen, no changes
#
# Prerequisites:
#   - openssl
#   - gh (GitHub CLI) authenticated: gh auth status
#   - docker compose, working from the iNova repo's compose file
#   - Three repos cloned at standard paths (set in CONFIG section below)

set -euo pipefail

# ─── CONFIG — adjust these to match your setup ──────────────────────
TARGET_URL="${TARGET_URL:-http://localhost:8000}"      # orchestrator URL
INOVA_DIR="${INOVA_DIR:-/Users/Sashi/Documents/projects/iNova}"
IBMIMCP_DIR="${IBMIMCP_DIR:-/Users/Sashi/Documents/projects/IBMiMCP}"
FLEET_DIR="${FLEET_DIR:-/Users/Sashi/Documents/projects/always-on-engineering-fleet}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.dev.yml}"   # in $INOVA_DIR

# ─── Args ───────────────────────────────────────────────────────────
SKIP_P1=false; SKIP_P2=false; SKIP_P3=false; DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --skip-phase-1) SKIP_P1=true ;;
    --skip-phase-2) SKIP_P2=true ;;
    --skip-phase-3) SKIP_P3=true ;;
    --dry-run)      DRY_RUN=true ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

# ─── Helpers ────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
say()   { echo -e "${BLUE}── $*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
fail()  { echo -e "${RED}✗ $*${NC}"; }

confirm() {
  local prompt="${1:-Continue?}"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] would prompt: $prompt — assuming yes"
    return 0
  fi
  read -rp "$prompt [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] $*"
  else
    eval "$@"
  fi
}

require() {
  command -v "$1" >/dev/null 2>&1 || { fail "missing required tool: $1"; exit 1; }
}

# ─── Preflight: tools and paths ─────────────────────────────────────
say "Preflight: checking tools and paths"
require openssl
require gh
require curl
require git
require docker
[[ -d "$INOVA_DIR" ]]    || { fail "iNova not at $INOVA_DIR";    exit 1; }
[[ -d "$IBMIMCP_DIR" ]]  || { fail "IBMiMCP not at $IBMIMCP_DIR"; exit 1; }
[[ -d "$FLEET_DIR" ]]    || { fail "fleet not at $FLEET_DIR";    exit 1; }
gh auth status >/dev/null 2>&1 || { fail "gh not authenticated — run 'gh auth login'"; exit 1; }
ok "tools and paths OK"
echo

# ════════════════════════════════════════════════════════════════════
# PHASE 1 — Secrets + verification
# ════════════════════════════════════════════════════════════════════
if [[ "$SKIP_P1" == "false" ]]; then
  say "PHASE 1 — Secrets + verification"

  # 1.1 Generate or detect QA_BYPASS_SECRET
  ENV_FILE="$INOVA_DIR/.env"
  if grep -q '^QA_BYPASS_SECRET=' "$ENV_FILE" 2>/dev/null; then
    EXISTING=$(grep '^QA_BYPASS_SECRET=' "$ENV_FILE" | cut -d= -f2-)
    if [[ "$EXISTING" =~ ^[a-f0-9]{64}$ ]]; then
      ok "QA_BYPASS_SECRET already set in $ENV_FILE (looks valid)"
      QA_BYPASS_SECRET="$EXISTING"
    else
      warn "QA_BYPASS_SECRET exists but doesn't look like a 64-char hex"
      confirm "Replace with a freshly generated one?" || { fail "aborting"; exit 1; }
      QA_BYPASS_SECRET=$(openssl rand -hex 32)
      run "sed -i.bak 's|^QA_BYPASS_SECRET=.*|QA_BYPASS_SECRET=$QA_BYPASS_SECRET|' '$ENV_FILE'"
      ok "rotated QA_BYPASS_SECRET"
    fi
  else
    QA_BYPASS_SECRET=$(openssl rand -hex 32)
    say "generated new QA_BYPASS_SECRET (64-char hex)"
    confirm "Append to $ENV_FILE?" || { fail "aborting"; exit 1; }
    run "printf '\n# QA bypass for always-on QA fleet — never share, never commit\nQA_BYPASS_SECRET=%s\n' '$QA_BYPASS_SECRET' >> '$ENV_FILE'"
    ok "added to $ENV_FILE"
  fi

  # 1.2 .gitignore safety
  GITIGNORE="$INOVA_DIR/.gitignore"
  if ! grep -qE '^\.env$' "$GITIGNORE" 2>/dev/null; then
    say "adding .env / .venv / qa-artifacts to .gitignore"
    confirm "OK to update .gitignore?" || { fail "aborting"; exit 1; }
    run "cat >> '$GITIGNORE' <<EOF

# Local secrets — NEVER commit
.env
.env--
.DS_Store
.venv/
qa-artifacts/
EOF"
    ok ".gitignore updated"
  else
    ok ".env already gitignored"
  fi

  # 1.3 Restart orchestrator (interactive — user picks)
  say "Orchestrator restart needed to pick up new env var"
  echo "  Compose file: $INOVA_DIR/$COMPOSE_FILE"
  if confirm "Restart orchestrator now via 'docker compose restart orchestrator'?"; then
    run "cd '$INOVA_DIR' && docker compose -f '$COMPOSE_FILE' restart orchestrator"
    say "waiting 10s for orchestrator to come up..."
    run "sleep 10"
    ok "restart issued — verify with: docker compose -f $COMPOSE_FILE logs orchestrator"
  else
    warn "skipping restart — you must restart manually before the bypass test will work"
  fi

  # 1.4 Bypass smoke test
  say "Testing QA bypass at $TARGET_URL"
  EMAIL="qa+$(date +%s)@inovaide-qa.com"
  TOKEN=$(echo -n "$EMAIL" | openssl dgst -sha256 -hmac "$QA_BYPASS_SECRET" | awk '{print $2}')

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] would curl $TARGET_URL/auth/signup with bypass header"
  else
    RESP=$(curl -sS -X POST "$TARGET_URL/auth/signup" \
      -H "Content-Type: application/json" \
      -H "X-QA-Bypass: $TOKEN" \
      -d "{\"email\":\"$EMAIL\",\"name\":\"QA Bot Test\",\"password\":\"TestPass123!\"}" 2>&1 || true)

    echo "Response: $RESP"
    if echo "$RESP" | grep -q "QA bypass"; then
      ok "bypass works — got the magic string"
    elif echo "$RESP" | grep -qiE '(verify|verification)'; then
      fail "bypass didn't fire — got verification flow. Likely causes:"
      echo "    - secret mismatch between .env and orchestrator process"
      echo "    - orchestrator didn't pick up env var (try restart again)"
      echo "    - email pattern doesn't match the bypass regex"
      confirm "Continue anyway?" || exit 1
    else
      fail "unexpected response — check orchestrator logs"
      confirm "Continue anyway?" || exit 1
    fi
  fi

  # 1.5 QA tenant accounts (interactive — needs DB password)
  echo
  say "Pre-provisioned QA accounts: qa-smoke@inovaide-qa.com, qa-explore@inovaide-qa.com"
  echo "  These don't match the bypass regex (qa+digits@), so they need DB-flagged is_verified."
  echo
  echo "MANUAL STEP — sign up these accounts via the UI, then run this SQL:"
  echo "  docker compose -f $COMPOSE_FILE exec postgres psql -U postgres -d inova"
  echo
  echo "  UPDATE users SET is_verified = TRUE"
  echo "  WHERE email IN ('qa-smoke@inovaide-qa.com', 'qa-explore@inovaide-qa.com');"
  echo
  warn "Make sure to save both passwords to your password manager NOW."
  confirm "Continue to Phase 2 (do tenant setup later)?" || exit 0

  ok "Phase 1 complete (with manual tenant setup pending)"
  echo
fi

# ════════════════════════════════════════════════════════════════════
# PHASE 2 — Labels + push
# ════════════════════════════════════════════════════════════════════
if [[ "$SKIP_P2" == "false" ]]; then
  say "PHASE 2 — Labels + commit + push"

  # 2.1 Create GitHub labels
  if confirm "Create QA-bot labels in iNova and IBMiMCP repos?"; then
    create_label() {
      local repo="$1" name="$2" color="$3" desc="$4"
      if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] would create/update label '$name' in $repo"
        return 0
      fi
      gh label create "$name" --color "$color" --description "$desc" --repo "$repo" 2>/dev/null \
        || gh label edit "$name" --color "$color" --description "$desc" --repo "$repo" 2>/dev/null || true
    }

    for REPO in "RSA-Data-Solutions/iNova" "RSA-Data-Solutions/IBMiMCP"; do
      say "labels for $REPO"
      create_label "$REPO" "qa-bot"                  "0E8A16" "Filed by always-on QA fleet"
      create_label "$REPO" "tool-bug"                "D93F0B" "IBMiMCP tool returned wrong result"
      create_label "$REPO" "platform-bug"            "B60205" "inovaide.com platform issue"
      create_label "$REPO" "needs-fix"               "FBCA04" "Triggers Sam-bot autofix"
      create_label "$REPO" "awaiting-human-review"   "5319E7" "Sam-bot proposed fix"
      create_label "$REPO" "has-proposed-fix"        "1D76DB" "PR exists for this issue"
      create_label "$REPO" "false-fix"               "B60205" "Sam-bot fix did not actually fix"
      create_label "$REPO" "regression-after-fix"    "B60205" "Test broke after a Sam fix merged"
      create_label "$REPO" "needs-human-review"      "FBCA04" "Out of Sam scope, human required"
      create_label "$REPO" "wip-fix-pushed"          "FBCA04" "Sam pushed partial fix branch"
      create_label "$REPO" "possibly-flaky"          "C5DEF5" "Sam could not reproduce"
      create_label "$REPO" "severity/P0"             "B60205" "Production-blocking"
      create_label "$REPO" "severity/P1"             "D93F0B" "High impact"
      create_label "$REPO" "severity/P2"             "FBCA04" "Medium impact"
      create_label "$REPO" "severity/P3"             "0E8A16" "Low impact / cosmetic"
      create_label "$REPO" "release-blocker"         "B60205" "Blocks the next release"
      create_label "$REPO" "outage"                  "B60205" "Site is down — operational"
      create_label "$REPO" "tenant-isolation"        "B60205" "Cross-tenant leak risk"
      create_label "$REPO" "security"                "B60205" "Security-relevant finding"
      create_label "$REPO" "auto-filed"              "C5DEF5" "Filed by automation"
      create_label "$REPO" "routine-explore-morning" "C5DEF5" ""
      create_label "$REPO" "routine-explore-midday"  "C5DEF5" ""
      create_label "$REPO" "routine-explore-evening" "C5DEF5" ""
      create_label "$REPO" "routine-chaos"           "C5DEF5" ""
      create_label "$REPO" "safe-auto-merge"         "0E8A16" "Sam may auto-merge if CI passes"
      create_label "$REPO" "extended-scope"          "FBCA04" "Sam-bot used Tier 3 budget"
      ok "$REPO done"
    done
  else
    warn "skipping label creation"
  fi

  # 2.2 Pre-flight safety check
  say "Pre-flight: scanning for accidentally pasted secret literals"
  SUSPECT=$(grep -rE 'QA_BYPASS_SECRET\s*=\s*["\x27]?[a-f0-9]{32}' "$INOVA_DIR" \
    --include="*.py" --include="*.yml" --include="*.yaml" --include="*.md" \
    --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.ruff_cache 2>/dev/null || true)
  if [[ -n "$SUSPECT" ]]; then
    fail "Secret literal found in source files:"
    echo "$SUSPECT"
    fail "Remove these before pushing!"
    exit 1
  fi
  ok "no secret literals in source"

  # 2.3 Commit + push iNova
  echo
  say "Staging iNova changes"
  cd "$INOVA_DIR"
  git status

  echo
  confirm "Stage qa/, auth.py, .gitignore, workflows-pending/ and commit?" || { warn "skipping iNova commit"; SKIP_INOVA=true; }

  if [[ "${SKIP_INOVA:-false}" != "true" ]]; then
    run "git add .gitignore"
    run "git add orchestrator/app/routers/auth.py"
    run "git add qa/"
    run "git add .github/workflows-pending/"

    if [[ "$DRY_RUN" == "false" ]] && git diff --cached --name-only | grep -qE '(^|/)(\.env|\.venv|qa-artifacts)(/|$)'; then
      fail "STOP: secrets or junk staged"
      run "git reset"
      exit 1
    fi

    run "git diff --cached --stat"
    confirm "Commit and push to iNova main?" || { run "git reset"; exit 1; }
    run "git commit -m 'feat(qa): always-on QA fleet scaffolding (workflows pending)

- qa/: Playwright + pytest harness (P0 suite, signup, rotation)
- qa/homelab/: cron smoke + 5-min health check + issue filer
- orchestrator/app/routers/auth.py: HMAC-gated email-verification bypass
- .github/workflows-pending/: routine triggers, activated after manual
  routine verification

Routines and Sam-bot specs live in always-on-engineering-fleet repo.'"
    run "git push origin main"
    ok "iNova pushed"
  fi

  # 2.4 Commit + push IBMiMCP
  echo
  say "Staging IBMiMCP changes"
  cd "$IBMIMCP_DIR"
  git status

  echo
  if confirm "Commit IBMiMCP workflow stubs?"; then
    run "git add .github/workflows-pending/"
    run "git diff --cached --stat"
    confirm "Push?" || { run "git reset"; exit 1; }
    run "git commit -m 'ci: stage QA fleet routine triggers (pending verification)

Workflows in workflows-pending/ — moved to workflows/ once Routines 4
and 5 are verified working via manual fires.'"
    run "git push origin main"
    ok "IBMiMCP pushed"
  else
    warn "skipping IBMiMCP commit"
  fi

  # 2.5 Commit + push fleet repo
  echo
  say "Staging fleet repo"
  cd "$FLEET_DIR"
  git status

  echo
  if confirm "Commit routines/ and scripts/watchdog/?"; then
    run "git add routines/"
    run "git add scripts/"
    run "git diff --cached --stat"
    confirm "Push?" || { run "git reset"; exit 1; }
    run "git commit -m 'feat(qa-fleet): max-bug-finding routine specs + watchdog

- routines/: 5-routine plan, Sam-bot autofix, max-bug-mode variant,
  Sam scope expansion
- scripts/watchdog/: macOS launchd-based heartbeat monitor
- scripts/setup/: phase-1-2-3 setup script'"
    run "git push origin main"
    ok "fleet pushed"
  else
    warn "skipping fleet commit"
  fi

  # 2.6 Confirm no actions fired
  echo
  say "Verifying no GitHub Actions fired from these pushes"
  if [[ "$DRY_RUN" == "false" ]]; then
    echo "Recent runs in iNova:"
    gh run list --repo RSA-Data-Solutions/iNova --limit 3
    echo "Recent runs in IBMiMCP:"
    gh run list --repo RSA-Data-Solutions/IBMiMCP --limit 3
    warn "If you see new runs from this script's commits, something fired unexpectedly. Check above."
  fi

  ok "Phase 2 complete"
  echo
fi

# ════════════════════════════════════════════════════════════════════
# PHASE 3 — Endpoint plumbing
# ════════════════════════════════════════════════════════════════════
if [[ "$SKIP_P3" == "false" ]]; then
  say "PHASE 3 — /health and /api/mcp/status endpoints"

  HEALTH_PY="$INOVA_DIR/orchestrator/app/routers/health.py"
  if [[ -f "$HEALTH_PY" ]]; then
    ok "health.py already exists at $HEALTH_PY"
  else
    fail "health.py missing — was it written by an earlier step?"
    fail "expected: $HEALTH_PY"
    exit 1
  fi

  echo
  warn "MANUAL EDIT REQUIRED — main.py wiring"
  echo
  echo "Open this file in your editor:"
  echo "    $INOVA_DIR/orchestrator/app/main.py"
  echo
  echo "1. In the imports block (near the top), add:"
  echo "       from app.routers import health"
  echo
  echo "2. In the router-inclusion block (where you see other"
  echo "   app.include_router(...) calls), add:"
  echo "       app.include_router(health.router)"
  echo
  echo "Both endpoints use absolute paths (/health and /api/mcp/status),"
  echo "so DO NOT add a prefix= argument to include_router."
  echo
  confirm "Done editing main.py?" || { warn "Phase 3 paused — finish main.py and re-run with --skip-phase-1 --skip-phase-2"; exit 0; }

  # 3.2 Restart and test
  echo
  if confirm "Restart orchestrator and test endpoints?"; then
    run "cd '$INOVA_DIR' && docker compose -f '$COMPOSE_FILE' restart orchestrator"
    say "waiting 10s..."
    run "sleep 10"

    echo
    say "Testing /health"
    if [[ "$DRY_RUN" == "false" ]]; then
      RESP=$(curl -sS -i "$TARGET_URL/health" 2>&1)
      echo "$RESP"
      if echo "$RESP" | grep -q '"status":"ok"'; then
        ok "/health returns 200 with expected body"
      else
        fail "/health didn't return expected body"
        fail "check 'docker compose logs orchestrator' for import errors"
      fi
    fi

    echo
    say "Testing /api/mcp/status"
    if [[ "$DRY_RUN" == "false" ]]; then
      RESP=$(curl -sS -i "$TARGET_URL/api/mcp/status" 2>&1)
      echo "$RESP"
      if echo "$RESP" | grep -q '"healthy"'; then
        ok "/api/mcp/status returns expected JSON"
        warn "  Note: server_reachable will be false until real MCP client is wired up"
      else
        fail "/api/mcp/status didn't return expected JSON"
      fi
    fi
  fi

  # 3.4 Commit + push the endpoint
  echo
  say "Committing endpoint changes"
  cd "$INOVA_DIR"
  git status -- orchestrator/app/

  echo
  if confirm "Commit and push health.py + main.py?"; then
    run "git add orchestrator/app/routers/health.py"
    run "git add orchestrator/app/main.py"
    run "git diff --cached --stat"
    confirm "Push?" || { run "git reset"; exit 1; }
    run "git commit -m 'feat(orchestrator): /health and /api/mcp/status endpoints

Public, unauthenticated endpoints for homelab QA probes.
- /health: minimal liveness check
- /api/mcp/status: reports IBMiMCP tool count for outage detection

The mcp_status endpoint uses a stub for tool_count until the real MCP
client handle is wired up — falls back gracefully so the endpoint
exists and homelab can poll without false outages.'"
    run "git push origin main"
    ok "endpoint changes pushed"
  fi

  # 3.5 Public URL test (optional)
  echo
  if confirm "Test endpoints from the public URL (https://inovaide.com)?"; then
    if [[ "$DRY_RUN" == "false" ]]; then
      echo
      curl -sS -i https://inovaide.com/health 2>&1 | head -10
      echo
      curl -sS -i https://inovaide.com/api/mcp/status 2>&1 | head -15
      echo
      warn "If these returned 404, your reverse proxy / Cloudflare needs to expose the new paths"
    fi
  fi

  ok "Phase 3 complete"
  echo
fi

# ════════════════════════════════════════════════════════════════════
# Done
# ════════════════════════════════════════════════════════════════════
say "All requested phases done"
echo
echo "Next steps (manual, when you're ready):"
echo "  • Phase 4: install homelab cron (qa/homelab/README.md)"
echo "  • Phase 5: create Routines 2, 3, 5, A, B, C, E in claude.ai/code/routines"
echo "  • Phase 6: move workflows-pending/ → workflows/ to activate triggers"
echo "  • Phase 7: install Mac launchd watchdog"
echo
echo "If anything went wrong, re-run with the appropriate --skip-phase-N flags"
echo "to resume from where you left off."
