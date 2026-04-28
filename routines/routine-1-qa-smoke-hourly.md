# Routine 1 — Hourly P0 Smoke + Deploy (`qa-smoke-hourly`)

Paste-ready spec for `claude.ai/code/routines`.

This is the updated Routine 1. Key changes from the previous version:
- Aaron deploys the inovaide.com stack from latest main before each run
  (targets Aaron-deployed local staging, not live inovaide.com)
- Sam fixes `code_bug` failures in-loop (was read-only in the previous version)
- `env_problem` and `flaky` failures are explicitly ignored here (Routine 3 owns them)
- A platform deploy failure files ONE ticket and stops cleanly — no QA against a broken build

---

## Routine name

`qa-smoke-hourly`

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: UTC (local time)
```

17 runs/day, :05 past every hour from 07:00 to 23:00 UTC.
Naturally avoids the 03:00–04:00 UTC pub400.com maintenance window.

---

## Repos to attach

Same three as all other routines:
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

---

## Environment variables (in routine settings panel, NOT the prompt)

```
QA_BASE_URL                = http://localhost:<port>   # Aaron-deployed local staging
QA_TENANT_SMOKE_PASSWORD   = <qa-smoke@inovaide-qa.com password>
```

Do NOT set this to the live `inovaide.com` URL — Aaron deploys staging locally
and QA runs against that. The live site is never touched by this routine.

---

## Prompt (paste this into the routine)

```
You are the orchestrator (Ram) for an hourly P0 smoke run against
Aaron-deployed local staging. No webhook payload — this is a scheduled
cron run.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    - always-on-engineering-fleet  (your operating manual)
    - iNova                        (source + QA suite)
    - IBMiMCP                      (MCP tool server)

STEP 1 — Read your manual.
Read these files (use absolute paths from STEP 0):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You will play Ram, Aaron, Lynn, and Sam sequentially in this session.
max_iterations: 3. enable_research: false.

STEP 2 — Act as Aaron (DevOps). Deploy from latest main.
Pull latest main for both repos:
    cd {iNova}   && git fetch origin && git checkout main && git pull origin main
    cd {IBMiMCP} && git fetch origin && git checkout main && git pull origin main

Deploy the inovaide.com stack per agents/aaron.md:
    1. Kill any stale server process holding the IBMiMCP port.
    2. Build IBMiMCP from source:  cd {IBMiMCP} && npm run build
    3. Start the server:           node dist/server.js &
    4. Wait for health check:      curl -s .../health → HTTP 200 or 404
    5. Smoke-test two representative tools (listActiveJobs, getSystemStatus).
    6. Issue a tools/list MCP call and count registered tools.

Verify IBMiMCP connection is healthy:
    - Health check passed (HTTP 200 or 404)
    - registered_tool_count ≥ 130

If Aaron reports FAILED **or** registered_tool_count < 130:
    File ONE GitHub issue in RSA-Data-Solutions/iNova:
        title:  "Aaron deploy failed — qa-smoke-hourly {UTC timestamp}"
        labels: qa-bot, platform-failure, severity/P0, needs-fix
        body:   Full Aaron devops-report output, UTC timestamp, registered_tool_count.
    Dedup: if an open issue already has this title (same UTC hour), comment on it
    instead of opening a new one.
    Write the heartbeat (STEP 6 below), then STOP.
    Do not run QA against a broken or incomplete build.

If Aaron reports READY: proceed to STEP 3.

STEP 3 — Act as Lynn (QA). Run the P0 suite.
Per agents/lynn.md, run the full P0 suite against the Aaron-certified server.
The server is already running — treat as server_already_running: true.

Run the P0 suite using the command from contexts/inova.md
(ui_journey_p0_suite_command). Concretely:
    cd {iNova}/qa
    python3 -m venv .venv 2>/dev/null; source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium 2>/dev/null
    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_TENANT_SMOKE=qa-smoke@inovaide-qa.com \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

This exercises all 12 P0 tools via the qa-smoke tenant against pub400.com.
Read /tmp/p0-report.json when complete.

Classify each failure per lynn.md Step 3:
    code_bug    — test ran, wrong output or wrong data
    env_problem — connectivity, missing file, permission denied
    flaky       — timing or non-deterministic

--- DEGRADATION CHECK (apply before filing individual tickets) ---

Condition A: ≥6 of the 12 P0 tools failed in THIS run.

Condition B: The SAME single P0 tool failed in THIS run AND in the
             immediately preceding hourly run. Determine the previous
             run's result by:
             a) Checking open GitHub issues for a dedup hash matching
                that tool filed within the last 90 minutes, OR
             b) Reading the previous heartbeat timestamp and cross-
                referencing the qa-report artifact if available.

If Condition A OR Condition B is true:
    File ONE issue in RSA-Data-Solutions/iNova:
        title:  "P0 SUITE DEGRADATION — {N} tools failing"
        labels: qa-bot, severity/P0, platform-failure, needs-fix
        body:   Full list of failing tools, failure types, raw error first lines.
    Skip all individual per-tool tickets for this run.
    Proceed to STEP 4 (Sam will attempt fixes per degradation ticket).

If neither condition:
    For each code_bug failure only:
        Apply lynn.md Step 5 ticket-filing rules.
        dedup_hash = sha256(target_repo + test_name + first_line(error) + tool_name)[:12]
        Search open issues in RSA-Data-Solutions/iNova for
        "Dedup hash: {hash}".
        If found: comment "Reoccurred at {timestamp} — qa-smoke-hourly run."
        If not: create issue per lynn.md schema.
        Labels: qa-bot, severity/Px, code-bug, needs-fix

Do NOT file tickets for env_problem or flaky failures — those belong to
Routine 3. Classify, note in session summary, then move on.

STEP 4 — Act as Sam (SE). Fix code_bug failures only.
Per agents/sam.md, for each code_bug failure identified by Lynn:

    1. Read related code with grep/file tools (do NOT guess).
    2. Form an explicit hypothesis.
    3. Make the smallest change that makes the failing test pass.
    4. Re-run the failing test — must now pass.
    5. Re-run adjacent tests in the same module — must still pass.
    6. Run the repo linter per CI config (ruff, eslint, etc.).

Scope hard limits (same as sam.md):
    - Max 5 files modified
    - Max 100 lines changed (additions + deletions)
    - NEVER touch CI/CD pipelines, auth, secrets, migrations, or fleet
      config (agents/, contexts/, SKILL.md) unless the issue carries
      `auth-touch-allowed` or `infra-allowed` applied by a human.

Ignore env_problem and flaky failures entirely — do not attempt fixes,
do not comment on them, leave them for Routine 3.

If Sam cannot fix a code_bug within scope:
    Add label `needs-human-review` to the issue.
    Remove label `needs-fix`.
    Note it in the session summary and move to the next failure.

STEP 5 — Push (if green).
Push authority is Ram's alone, per agents/ram.md git safety rules.

Push only when ALL three conditions hold:
    1. Every targeted code_bug test now passes after Sam's fixes.
    2. No new test regressions were introduced.
    3. ZERO open severity/P0 issues in iNova or IBMiMCP were filed
       by this run (includes the degradation ticket and Aaron-failed ticket).

If any severity/P0 issue is open from this run: do NOT push.
Leave Sam's fixes on the working branch for human review.

If all conditions met:
    git add <specific files changed by Sam — NOT git add -A>
    git commit -m "fix: hourly P0 smoke fixes — {tool list} [{UTC timestamp}]"
    git push origin main

STEP 6 — Heartbeat.
Append the current UTC ISO timestamp (one line) to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt

Commit with message:
    "heartbeat: qa-smoke-hourly {UTC timestamp}"
Push to the fleet repo's main branch.

The external watchdog reads this file on every run. A missing heartbeat
triggers a silent-failure alert. Always write the heartbeat — even if
earlier steps failed or the run was aborted.

Hard limits (terminal — stop after writing the heartbeat if any are hit):
- Total run time cap: 25 minutes. If exceeded, file ONE severity/P1 issue:
  title: "qa-smoke-hourly timed out at STEP N — {UTC timestamp}"
  then write heartbeat and stop.
- Never log or commit QA_TENANT_SMOKE_PASSWORD, bypass tokens, or secrets.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
- Do NOT push to main if any severity/P0 issue is open from this run.
```

---

## What changed from the previous Routine 1

| | Previous `qa-smoke-hourly` | This version |
|---|---|---|
| Target URL | Live inovaide.com | Aaron-deployed local staging |
| Pre-QA step | None | Aaron deploys from main + verifies tool count ≥ 130 |
| Sam role | Read-only triage | Fixes `code_bug` failures (max 5 files / 100 lines) |
| `env_problem` / `flaky` | Filed as issues | Ignored — Routine 3 owns them |
| Deploy failure path | N/A | Files ONE `platform_failure` ticket and stops |
| Push guard | N/A | No push if any P0 ticket is open from this run |
| Run time cap | 20 minutes | 25 minutes (Aaron deploy adds ~5 min) |

---

## Cap accounting

```
R1 hourly smoke (this routine)   17 runs/day  (68% of Team plan)
R2 signup daily                   1 run/day   (4%)
R3 explore daily                  1 run/day   (4%)
R4 post-deploy regression         webhook (variable)
R5 Sam auto-fix on issue          webhook (variable)
                                 ─────────────
total scheduled:                 19 runs/day  (76%)
```

Aaron's build step adds ~5 minutes to each of the 17 daily R1 sessions.
Set the routine's run time cap to 25 minutes to accommodate.
