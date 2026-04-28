# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

**ID:** `qa-smoke-hourly`  
**Schedule:** `5 7-23 * * *` — :05 past every hour, 07:00–23:00 local  
**Repo:** `RSA-Data-Solutions/always-on-engineering-fleet`

---

## Purpose

Hourly safety net for the P0 tool suite. Each run:

1. Deploys fresh from latest `main` (Aaron)
2. Runs all 12 P0 tools via the qa-smoke tenant against pub400.com (Lynn)
3. Fixes any `code_bug` failures in-session (Sam, up to 3 iterations)
4. Pushes clean fixes if no P0 ticket is open (Ram)
5. Writes a heartbeat the external watchdog reads to confirm the routine ran

`env_problem` and `flaky` failures are **not** fixed here — they belong to Routine 3.

---

## Setup

### Repos attached
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

### Environment variables (routine env panel — not in the prompt)

| Variable | Value |
|----------|-------|
| `QA_TENANT_SMOKE_PASSWORD` | qa-smoke@inovaide-qa.com password |

Aaron provides the certified server URL at runtime; `QA_BASE_URL` is not preset.

---

## Schedule

```
Cron:     5 7-23 * * *
```

17 runs/day. The cron window ends before the 03:00–04:00 UTC pub400 maintenance
window, so no explicit maintenance-window check is needed in the prompt.

---

## Prompt (paste into the routine)

```
You are Ram — orchestrator of the always-on engineering fleet.

STEP 0 — Discover repo paths.
  ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    fleet  →  always-on-engineering-fleet
    inova  →  iNova
    ibmi   →  IBMiMCP

STEP 1 — Read your manual.
Read (absolute paths):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You play Ram, Aaron, Lynn, and Sam sequentially. max_iterations=3.

STEP 2 — Act as Aaron (deploy).
Per agents/aaron.md, deploy the inovaide.com stack from latest main:
    1. git pull origin main  (iNova + IBMiMCP)
    2. Build and start the inovaide.com stack
    3. Verify IBMiMCP connection:
           - MCP server reachable
           - registered_tool_count >= 130
    4. Write deploy report:
           /tmp/aaron-deploy-report.json
           { "status": "READY"|"FAILED",
             "server_url": "http://...",
             "registered_tool_count": N,
             "error": "..." }

    If status == FAILED:
        File ONE issue in RSA-Data-Solutions/iNova:
            title:  "Aaron deploy failed"
            labels: qa-bot, platform-bug, severity/P0, platform_failure
            body:   error details + session URL
        STOP — do not run QA against a broken build.

STEP 3 — Act as Lynn (P0 suite).
Per agents/lynn.md, run all 12 P0 tools via the qa-smoke tenant
against the Aaron-certified server and pub400.com backend:
    cd {inova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=$(jq -r .server_url /tmp/aaron-deploy-report.json) \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

    For each failure in /tmp/p0-report.json — apply Step 5 ticket-filing
    rules from lynn.md:
        - Compute dedup_hash = sha256(repo+test_name+first_line(error)+tool_name)[:12]
        - Search open issues for "Dedup hash: {hash}"
        - If found: comment "Reoccurred at {now} in qa-smoke-hourly."
        - If not found: create issue per lynn.md schema
        Labels: qa-bot, severity/Px (and code_bug / env_problem / flaky as appropriate)

STEP 4 — Act as Sam (fix code_bug only — max_iterations=3).
Per agents/sam.md — fix ONLY failures classified as code_bug. Do NOT
fix env_problem or flaky (those belong to Routine 3).

For each code_bug iteration (up to 3):
    - Read related source code (grep / ast, don't guess)
    - Make the smallest change that fixes the test
    - Re-run the failing test — must pass
    - Re-run adjacent tests — no regressions
    - Run repo linters per the CI config
    If fix scope > 5 files or > 100 lines: add needs-human-review label,
    push the branch without opening a PR, and stop that bug.

STEP 5 — Degradation check.
After Lynn's run, evaluate:
    a) >=6 of 12 P0 tools failed in this single run, OR
    b) Same single P0 tool failed in this AND the previous hourly run.

If either condition is true:
    - Close / suppress any individual tickets just filed for those tools
    - Open ONE severity/P0 issue in RSA-Data-Solutions/iNova:
          title:  "P0 SUITE DEGRADATION"
          labels: qa-bot, severity/P0, platform_failure
          body:   failing tool list + session URL
    (File this instead of up to 12 individual tickets.)

STEP 6 — Push (green builds only).
Ram pushes via normal git authority. Push condition:
    - Zero open P0 tickets exist in iNova or IBMiMCP repos AND
    - Sam's changes (if any) pass all tests with no regressions
If any P0 ticket is open: log "push skipped — P0 open" and do not push.
Never force-push; never push directly to main without a passing test run.

STEP 7 — Heartbeat.
Write the current UTC ISO timestamp to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
Format:
    {timestamp}
    routine=qa-smoke-hourly
    outcome=PASS|FAIL|DEPLOY_FAILED
    p0_pass={N}/12
    tickets_filed={N}
Commit: "heartbeat: qa-smoke-hourly {timestamp}"
Push to the fleet repo's main branch.
The external watchdog reads this file; a missing or stale heartbeat
signals a silent routine failure.

Hard limits:
- Total run time cap: 20 minutes. If exceeded, file ONE severity/P1
  issue "qa-smoke-hourly timed out at STEP N" and write the heartbeat.
- Never log QA passwords, secrets, or bypass tokens.
- Do NOT touch baseline_metrics.json — only Routine 4 updates that.
- Do NOT push to main without a clean post-fix test run.
```

---

## Heartbeat file

`fleet-workspace/heartbeats/qa-smoke-hourly.txt`

Written by STEP 7 of each run. The external watchdog expects this file
to be updated every hour during the 07:05–23:05 window. A gap of ≥2
hours during that window indicates a missed run.

---

## Cap accounting

| Routine | Runs/day | % of Team cap (25/day) |
|---------|----------|------------------------|
| R1 (this) | 17 | 68% |
| R2 signup | 1 | 4% |
| R3 explore | 1 | 4% |
| R4 post-deploy | webhook | variable |
| **Total** | **19 scheduled** | **76%** |

---

## Differences from previous version (`routines-1-2-3.md`)

| Aspect | Previous | This version |
|--------|----------|--------------|
| Aaron step | absent — ran against live inovaide.com | Added as STEP 2 — deploys local staging |
| Sam role | read-only triage | Fixes `code_bug` failures (max 3 iterations) |
| Push gate | always pushed | Skips push if any P0 ticket is open |
| Heartbeat format | timestamp only | Structured (outcome, p0_pass, tickets) |
| Maintenance window | explicit check in prompt | Eliminated — cron ends before 03:00 UTC |
