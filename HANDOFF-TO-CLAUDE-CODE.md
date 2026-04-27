# Handoff to Claude Code — Finish QA Fleet Setup (Phases 1-3)

## Your job

Pick up a partially-completed setup of an always-on QA fleet for inovaide.com.
The user has been working through a 7-phase setup plan with another Claude
instance. Phases 1-3 are partially done. Finish them, then stop. Do **not**
proceed to Phases 4-7 — those need separate human review.

## Quick context

The user is Sashi, building an autonomous QA system for inovaide.com (a
multi-tenant platform that lets users run agentic workflows against IBM i
systems via the IBMiMCP server). The fleet finds bugs, files GitHub issues,
auto-fixes via a Sam-bot routine, and verifies via post-deploy regression.

Three repos are involved, all under `RSA-Data-Solutions`:

- `iNova` — the platform itself (`/Users/Sashi/Documents/projects/iNova`)
- `IBMiMCP` — the MCP server (`/Users/Sashi/Documents/projects/IBMiMCP`)
- `always-on-engineering-fleet` — agent definitions and routine specs
  (`/Users/Sashi/Documents/projects/always-on-engineering-fleet`)

## Current state — what's done

✅ `qa/` Playwright suite written under `iNova/qa/`
✅ Homelab cron scripts written under `iNova/qa/homelab/`
✅ `orchestrator/app/routers/auth.py` has QA bypass HMAC code wired in
✅ `orchestrator/app/routers/health.py` exists (new file, not yet wired)
✅ Workflow YAMLs staged in `iNova/.github/workflows-pending/` and
   `IBMiMCP/.github/workflows-pending/` (not active — moved out of
   `workflows/` so they don't fire on push)
✅ Routine specs and watchdog scripts in `always-on-engineering-fleet/`
✅ Phase 1 (Phase 1 = bypass secret + verification) was completed
✅ GitHub labels were created in both repos
✅ The `phase-1-2-3.sh` setup script exists at
   `always-on-engineering-fleet/scripts/setup/phase-1-2-3.sh`
✅ Routine 4 was created in claude.ai/code/routines and verified via
   manual fire (the user got a session URL, the prompt parsed)

## Current state — what's NOT done (your work)

The user attempted to run the setup script. The script's `git add` calls
didn't take effect (eval quoting bug). The user then tried manual
`git push` on the fleet repo and got rejected because remote has commits
the local doesn't have.

So the immediate problems:

1. **Fleet repo push rejected** — remote ahead of local, needs rebase
2. **iNova has uncommitted changes**:
   - Untracked: `orchestrator/app/routers/health.py`
   - "Deleted": `.github/workflows/qa-bot-fix-trigger.yml` and
     `.github/workflows/release-qa.yml` (these were moved to
     `workflows-pending/`, but git sees the old paths as deleted +
     new paths as untracked since the move was never staged)
   - Other unstaged changes likely include `qa/`, modifications to
     `auth.py`, and `.gitignore` updates
3. **IBMiMCP** — same workflow moves need to be committed
4. **`orchestrator/app/main.py`** has NOT been edited yet to wire in
   the new `health` router — the user paused at this step

## What you need to do, in order

### Step 1: Verify the working state

Run these and confirm before proceeding:

```bash
cd /Users/Sashi/Documents/projects/iNova
git status
git log --oneline -5

cd /Users/Sashi/Documents/projects/IBMiMCP
git status
git log --oneline -5

cd /Users/Sashi/Documents/projects/always-on-engineering-fleet
git status
git log --oneline -5
git fetch origin
git log --oneline origin/main -5
```

Show the output to the user before acting. Confirm assumptions about what's
ahead/behind on each repo.

### Step 2: Resolve the fleet repo divergence

```bash
cd /Users/Sashi/Documents/projects/always-on-engineering-fleet
git pull --rebase origin main
```

If the rebase reports conflicts:

- Files under `fleet-workspace/` (heartbeats, proposals, iteration reports)
  are workspace artifacts — accept remote with `git checkout --theirs <path>`
- Files under `routines/`, `scripts/`, `agents/`, `contexts/`, or the root
  (SKILL.md, README.md, etc.) — show the conflict to the user, do NOT
  resolve unilaterally

If `--abort` is needed, do that and tell the user.

### Step 3: Verify the QA bypass landed in auth.py

The bypass wiring should already be in
`orchestrator/app/routers/auth.py`. Verify by checking for:

- `import hmac` near the top
- `import os` near the top
- `import re` near the top
- A function `_is_qa_bypass(email, header_token)` that does HMAC-SHA256
  comparison
- Inside the signup handler, after user creation, a call like:
  ```python
  if _is_qa_bypass(user.email, request.headers.get("X-QA-Bypass")):
      user.is_verified = True
      ...
      return MessageResponse(message="Account created (QA bypass — verified).")
  ```
- The OLD broken snippet (with `import hmac, os` mid-file and undefined
  `db.commit()`) should be REMOVED — verify it's not at the bottom.

If anything's missing or the broken snippet remains, fix and report what
you changed.

### Step 4: Wire the health router into main.py

The user has not done this yet. Edit
`/Users/Sashi/Documents/projects/iNova/orchestrator/app/main.py`:

1. Find the imports section that pulls in routers
   (look for `from app.routers import ...` or similar)
2. Add `health` to the imports — match the existing import style
3. Find where `app.include_router(...)` is called for other routers
4. Add: `app.include_router(health.router)` — **NO prefix argument**.
   The endpoints are absolute (`/health` and `/api/mcp/status`)

Show the user the diff before saving.

### Step 5: Stage and commit iNova

```bash
cd /Users/Sashi/Documents/projects/iNova

# Stage the new + modified files
git add .gitignore
git add orchestrator/app/routers/auth.py
git add orchestrator/app/routers/health.py
git add orchestrator/app/main.py
git add qa/

# Stage the workflow moves (deletes old paths + adds workflows-pending/)
git add .github/workflows/
git add .github/workflows-pending/

# Verify nothing dangerous is staged
git diff --cached --name-only | grep -E '\.env|\.venv|qa-artifacts|\.DS_Store' \
  && echo "STOP — secrets/junk staged" \
  || echo "clean"

# Show the user the diff stat
git diff --cached --stat
```

Stop here and confirm with the user before committing. If the user
approves:

```bash
git commit -m "feat(qa): always-on QA fleet scaffolding (workflows pending)

- qa/: Playwright + pytest harness (P0 suite, signup, rotation)
- qa/homelab/: cron smoke + 5-min health check + issue filer
- orchestrator/app/routers/auth.py: HMAC-gated email-verification bypass
- orchestrator/app/routers/health.py: /health and /api/mcp/status endpoints
- orchestrator/app/main.py: wire in health router
- .github/workflows-pending/: routine triggers, activated after manual
  routine verification

Routines and Sam-bot specs live in always-on-engineering-fleet repo."
git push origin main
```

If push is rejected, do `git pull --rebase origin main` first, then push.

### Step 6: Stage and commit IBMiMCP

```bash
cd /Users/Sashi/Documents/projects/IBMiMCP
git status
git add .github/workflows/      # stages the deletion
git add .github/workflows-pending/

git diff --cached --stat
```

Show the user, get approval, then:

```bash
git commit -m "ci: stage QA fleet routine triggers (pending verification)

Workflows in workflows-pending/ — moved to workflows/ once Routines 4
and 5 are verified working via manual fires."
git push origin main
```

### Step 7: Stage and commit fleet repo (after rebase from Step 2)

```bash
cd /Users/Sashi/Documents/projects/always-on-engineering-fleet
git status
git add routines/
git add scripts/
git add HANDOFF-TO-CLAUDE-CODE.md   # this file

git diff --cached --stat
```

Show the user, get approval, then:

```bash
git commit -m "feat(qa-fleet): max-bug-finding routine specs + watchdog + setup

- routines/: 5-routine plan, Sam-bot autofix, max-bug-mode variant,
  Sam scope expansion
- scripts/watchdog/: macOS launchd-based heartbeat monitor
- scripts/setup/: phase-1-2-3 setup script + README
- HANDOFF-TO-CLAUDE-CODE.md: handoff for picking up partial setup"
git push origin main
```

### Step 8: Restart orchestrator and test endpoints

The user's orchestrator runs via Docker Compose. The compose file is
`docker-compose.dev.yml` in the iNova repo root.

```bash
cd /Users/Sashi/Documents/projects/iNova
docker compose -f docker-compose.dev.yml restart orchestrator
sleep 10

# Test endpoints
curl -i http://localhost:8000/health
curl -i http://localhost:8000/api/mcp/status
```

Expected:
- `/health` returns `200` with `{"status":"ok"}`
- `/api/mcp/status` returns `200` with JSON containing `"healthy"`,
  `"server_reachable"`, `"tool_count"`, `"expected_min"`. The first
  two will likely be `false` and `0` since the real MCP client isn't
  wired up yet — the endpoint stubs gracefully.

If either returns 404 or the orchestrator fails to start, check
`docker compose logs orchestrator` for ImportError or routing
mismatches. The most likely failure mode is the `from app.routers
import health` line not matching the existing import style — adjust
to match.

### Step 9: Verify and stop

Run `git status` in all three repos. All should show "nothing to commit,
working tree clean" except for any files under
`fleet-workspace/heartbeats/` or `qa-artifacts/` which are normally
ignored.

Confirm to the user:
- ✅ All three repos pushed cleanly to GitHub
- ✅ Both /health and /api/mcp/status endpoints responding
- ✅ QA bypass code in place and previously verified

Then **STOP**. Do not proceed to Phase 4 (homelab cron install),
Phase 5 (creating Routines 2/3/5/A/B/C/E in claude.ai/code/routines),
Phase 6 (activating workflows by moving them out of workflows-pending/),
or Phase 7 (Mac launchd watchdog install). Those phases need a separate
session with the user.

## Things to NOT do

- **Do not move files out of `workflows-pending/` back into `workflows/`.**
  That's Phase 6 work. Moving them now would auto-fire Routine 4 and
  Routine 5 (when issues get filed), which the user wants to do
  deliberately later.
- **Do not commit any `.env`, `.venv/`, `qa-artifacts/`, or `.DS_Store`.**
  The script has guards but you should also visually verify before each
  commit.
- **Do not modify `agents/*.md` or `contexts/*.md` or `SKILL.md` in the
  fleet repo** unless the user asks. Those are Sashi's prompts.
- **Do not auto-merge anything.** All pushes are to `main` directly
  (this is a small team), but no PR auto-merge.
- **Do not install homelab cron jobs.** Phase 4. Separate session.
- **Do not run any `gh issue create`** or anything that triggers the
  qa-bot label workflow — Routine 5 doesn't exist yet, and the trigger
  YAML is in `workflows-pending/` so it's inactive, but be cautious.

## Reference files for context (read-only)

If you need more context on how a piece works:

- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/SKILL.md`
- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/agents/lynn.md`
- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/agents/sam.md`
- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/contexts/inova.md`
- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/routines/routines-final.md`
- `/Users/Sashi/Documents/projects/always-on-engineering-fleet/routines/routines-max-bug-mode.md`
- `/Users/Sashi/Documents/projects/iNova/qa/homelab/README.md`
- `/Users/Sashi/Documents/projects/iNova/qa/homelab/HEALTH-CHECK-README.md`

## If something feels off

If at any point the situation diverges meaningfully from this brief —
files exist that shouldn't, files are missing that should be there, the
git history shows commits you don't recognise — **stop and ask the user**
before continuing. The previous Claude session and the user did a lot
of back-and-forth, and there may be local state I'm not aware of.

## Done state

The user is done with you when:

1. Three repos pushed cleanly to GitHub
2. `git status` clean in all three
3. `/health` and `/api/mcp/status` returning expected responses from
   `http://localhost:8000` (or whatever `TARGET_URL` they're using)
4. Confirmation message to user: "Phases 1-3 complete. Ready for Phase 4
   (homelab cron) and Phase 5 (Routine creation) when you are."
