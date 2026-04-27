# Routine 1 — Hourly Smoke (`qa-smoke-hourly`)

This file supersedes the Routine 1 definition in `routines-1-2-3.md`.

Key changes from the previous version:
- **Aaron deploys first** — tests run against a freshly-deployed local staging build,
  not the live `inovaide.com` URL. Failures in deployment stop the routine before QA fires.
- **Sam fixes `code_bug` failures** — the routine is no longer read-only. `env_problem`
  and `flaky` classifications are ignored here and deferred to Routine 3.
- **Degradation gate** — fires on ≥ 6/12 tool failures in a single run, OR on the same
  single tool failing in two consecutive hourly runs. Reads `fleet-workspace/qa-smoke-state.json`
  to track the previous run's failures for the consecutive-run check.
- **Push gate** — Ram pushes green fixes only when zero open P0 tickets exist in iNova.

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (server-local time)
```

Runs at :05 past every hour from 07:00 to 23:00. The cron range avoids the
03:00–04:00 UTC pub400.com maintenance window.

---

## Setup checklist (one-time)

The routine needs these attached to it in the Routines UI:

**Repos attached:**
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

**GitHub connector:** issues:write + PR access on all three repos.

**Environment variables** (set in the routine env panel, never in the prompt):
```
QA_BASE_URL           = (set at runtime to Aaron's deployed local URL, e.g. http://localhost:8000)
QA_TENANT_SMOKE_PASSWORD = (qa-smoke@inovaide-qa.com password)
IBMIMCP_ADMIN_API_KEY = 3a309d556b6b6cd874a1f964b9b336e946e10aa0bc70651d
```

---

## Prompt

Paste this verbatim into the Routine's prompt field:

```
You are Ram, orchestrator of the always-on engineering fleet, running an
hourly P0 smoke against a freshly-deployed local staging build.

max_iterations: 3
enable_research: false

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 0 — Discover repo paths
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:
    ls -la ~ /workspace 2>/dev/null

Identify the absolute paths to:
    {fleet}   — always-on-engineering-fleet
    {iNova}   — iNova
    {ibmimcp} — IBMiMCP

All subsequent steps use these paths.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — Read your manuals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read these files before doing anything else:
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md

You play Ram, Aaron, Lynn, and Sam sequentially in this single session.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — Act as Aaron (deploy & health-gate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Per agents/aaron.md, deploy the inovaide.com stack from the latest main
branch of both iNova and IBMiMCP:

    # Pull latest main in both repos
    cd {ibmimcp} && git fetch origin && git checkout main && git pull origin main
    cd {iNova}   && git fetch origin && git checkout main && git pull origin main

    # Build and start IBMiMCP
    cd {ibmimcp} && npm run build
    pkill -f "node dist/server.js" || true && sleep 2
    PORT=3051 ADMIN_API_KEY=$IBMIMCP_ADMIN_API_KEY node dist/server.js &
    sleep 5

    # Build and start iNova orchestrator
    cd {iNova} && docker compose -f docker-compose.dev.yml up -d --build
    sleep 10

Health checks (per aaron.md):

    1. IBMiMCP /health → expect HTTP 200 or 404 (server up = pass).

    2. IBMiMCP tools/list → count registered tools.
       GATE: registered_tool_count MUST be ≥ 130.
       If count < 130, treat this as FAILED.

    3. Run 2 endpoint smoke tests against IBMiMCP (listActiveJobs,
       getSystemStatus) per aaron.md Step 5.

    4. iNova orchestrator health → curl http://localhost:8000/health.
       Expect HTTP 200.

Write deployment report to:
    {fleet}/fleet-workspace/iteration-1/devops-report.json

IF Aaron reports overall_status = FAILED:
    - File ONE GitHub issue in RSA-Data-Solutions/iNova:
        title:  "Aaron deploy failed — qa-smoke-hourly {UTC timestamp}"
        labels: qa-bot, platform-failure, severity/P0
        body:   Include devops-report.json summary: what failed, last
                20 lines of build output, health check result,
                registered_tool_count (if reachable), session URL.
    - Write heartbeat (STEP 5) with status=deploy_failed.
    - STOP. Do not proceed to QA.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — Act as Lynn (run the P0 suite)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Aaron has certified the local staging server. QA_BASE_URL for this run
points to the Aaron-deployed local server (not the live inovaide.com).
Use whatever port Aaron confirmed in devops-report.json.

Run the P0 suite:
    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=<Aaron-confirmed staging URL> \
    QA_TENANT=qa-smoke \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

The P0 suite exercises all 12 P0 tools via the qa-smoke tenant against
pub400.com. Wait for completion; do not kill it early.

── Degradation check ──────────────────────────

Read the previous-run state file (if it exists):
    {fleet}/fleet-workspace/qa-smoke-state.json

From /tmp/p0-report.json, collect the list of failing tool names
(extract from `tool_name` field in each failing test, or from the test
name if tool_name is absent).

DEGRADATION CONDITIONS (evaluate BEFORE filing individual tickets):

  A. ≥ 6 of the 12 P0 tools failed in this single run, OR
  B. The SAME single tool name appears in BOTH:
       - this run's failing list
       - the previous run's failing list (from qa-smoke-state.json)

If EITHER condition is true:
    File ONE severity/P0 issue in RSA-Data-Solutions/iNova:
        title:  "P0 SUITE DEGRADATION — {count} tools failing"
        labels: qa-bot, severity/P0, p0-suite-degradation
        body:   Failing tool list, failure types, this session URL,
                whether triggered by condition A or B (or both),
                link to previous run's state if condition B.
    Skip individual ticket filing for this run.
    Go to STEP 4.

If neither degradation condition is met:
    For each test in /tmp/p0-report.json with failure_type = "code_bug":
      - Apply Lynn's Step 5 ticket-filing rules (lynn.md)
      - dedup_hash = sha256("iNova" + test_name + first_line(error) + tool_name)[:12]
      - Search open issues in RSA-Data-Solutions/iNova for
        "Dedup hash: {hash}"
        - Found: comment "Reoccurred at {now} on qa-smoke-hourly."
        - Not found: create issue per lynn.md schema,
          labels: qa-bot, severity/Px (P0 for P0 tools, P1 otherwise)

    For failures with failure_type = "env_problem" or "flaky":
      - Do NOT file tickets. These belong to Routine 3.
      - Record them in the state file (STEP 5) for trend visibility.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — Act as Sam (fix code_bug failures only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sam is active (not read-only) in this routine, but scope is narrow.

For each code_bug ticket filed or found in STEP 3:
    Per agents/sam.md:
    - Read the failing test and its error
    - Identify the root-cause source file(s) in {iNova} or {ibmimcp}
    - Make the smallest change that fixes the test
    - Re-run the failing test — must pass
    - Run adjacent tests — must not regress
    - Run linters per the repo's CI config

    Hard limits (same as sam.md):
    - Max 5 files modified per bug
    - Max 100 lines changed per bug
    - NEVER push directly to main
    - NEVER touch CI/CD pipelines, secrets, or auth code
    If a fix would exceed these limits: add label `needs-human-review`
    to the issue, skip the fix, and continue to the next bug.

Ignore ALL env_problem and flaky failures — do not attempt fixes.
Those belong to Routine 3's daily exploratory run.

── Push gate ──────────────────────────────────

Before pushing any fix:
    Search open GitHub issues in RSA-Data-Solutions/iNova for
    label: severity/P0

    If ANY open P0 issue exists:
        Do NOT push. Stage the changes, write a note in the heartbeat
        that "fixes staged but withheld: open P0 tickets exist."
        A human must clear P0s before Sam's fixes can land.

    If zero open P0 issues:
        Ram pushes each fix branch:
            git add <targeted files only>
            git commit -m "fix({area}): {description} [qa-smoke-hourly]"
            git push origin <branch>
        Then opens a PR per sam.md Step 5. Do NOT auto-merge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — Write state file and heartbeat
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Update the state file for the next run's consecutive-failure check:
    {fleet}/fleet-workspace/qa-smoke-state.json

Format:
    {
      "last_run_utc": "<ISO timestamp>",
      "failing_tools": ["tool_name_1", "tool_name_2"],
      "deploy_status": "ok | deploy_failed",
      "degradation_fired": false,
      "session_url": "<this session's URL>"
    }

Write the heartbeat. The external watchdog reads this file; a missing
or stale heartbeat signals a silent routine failure.

    Append the current UTC ISO timestamp (one line) to:
        {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt

Commit both files with message:
    "heartbeat: qa-smoke-hourly {timestamp}"

Push to the fleet repo's main branch.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hard limits
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Total run cap: 25 minutes. If exceeded, file ONE severity/P1 issue
  "Routine 1 timed out at {step}" in iNova and write the heartbeat.
- Never log secrets, passwords, bypass tokens, or API keys.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
- Do NOT force-push or skip git hooks.
- Do NOT auto-merge any PR — human review is required.
```

---

## State file

The routine maintains `fleet-workspace/qa-smoke-state.json` across runs so that
the consecutive-failure degradation check (condition B above) can compare the current
run's failing tools against the previous run. This file is committed alongside the
heartbeat at the end of every run, including deploy-failed runs.

On the very first run, no state file exists — skip condition B and only evaluate
condition A.

---

## Cap accounting

```
Routine 1 (qa-smoke-hourly)  17 runs/day at :05 past each hour 07–23
                              68% of Team plan (25/day) cap
                              Leaves 8 slots/day for R2, R3, R4, R5
```

---

## Differences from previous Routine 1 (routines-1-2-3.md)

| Aspect | Old (routines-1-2-3.md) | New (this file) |
|--------|------------------------|-----------------|
| Target | Live `inovaide.com` | Aaron-deployed local staging |
| Aaron step | None | STEP 2 — deploy + health gate |
| Tool count gate | None | registered_tool_count ≥ 130 |
| Sam role | Read-only triage only | Fixes `code_bug` failures |
| Push authority | No push | Ram pushes if zero open P0s |
| env_problem / flaky | Downgrade in report | Explicitly deferred to Routine 3 |
| Consecutive-run check | Not tracked | qa-smoke-state.json persists |
