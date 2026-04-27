# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

Paste-ready spec for `claude.ai/code/routines`.

## Routine name

`qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: Local (Central Time)
```

Fires at :05 past every hour from 07:05 to 23:05 local time, giving
17 runs/day. The cron window naturally avoids pub400.com maintenance
(03:00–04:00 UTC / ~21:00–22:00 CT previous night falls outside the
7–23 window).

## Repos to attach

- RSA-Data-Solutions/always-on-engineering-fleet
- RSA-Data-Solutions/iNova
- RSA-Data-Solutions/IBMiMCP

## Environment variables (set in routine settings, not the prompt)

```
QA_BASE_URL                  # Aaron-deployed local staging URL
QA_TENANT_SMOKE_PASSWORD     # Password for the qa-smoke tenant
```

## Prompt (paste this into the routine)

```
You are Ram, the orchestrator of the always-on engineering fleet.
This is an hourly P0 smoke run: deploy, certify the stack, run the
P0 suite, triage, fix code bugs, and record a heartbeat.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    - always-on-engineering-fleet  (your fleet repo / operating manual)
    - iNova                        (app under test)
    - IBMiMCP                      (MCP server under test)

STEP 1 — Read your manual.
Read (use absolute paths from STEP 0):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md

STEP 2 — Aaron: deploy and certify the stack.
Spawn Aaron (agents/aaron.md) as a subagent. Pass:
    repo_path:   {iNova path}
    git_ref:     origin/main
    deploy_cmd:  (per contexts/inova.md — the inovaide.com stack)
    post_deploy_checks:
      - IBMiMCP connection healthy (health endpoint returns 200)
      - registered_tool_count >= 130
    output_path: {fleet}/fleet-workspace/smoke-latest/aaron-report.json

Wait for Aaron to complete. Read aaron-report.json.

If Aaron reports overall_status == FAILED:
    - File ONE issue in RSA-Data-Solutions/iNova with:
        title:  "Aaron deploy failed — qa-smoke-hourly"
        labels: platform_failure, severity/P0, qa-bot
        body:   Include Aaron's error summary and session URL.
    - Write the heartbeat (STEP 7) and STOP.
      Do NOT run QA against a broken build.

STEP 3 — Lynn: run the P0 suite.
Spawn Lynn (agents/lynn.md) as a subagent. Pass:
    server_already_running: true
    base_url:    (QA_BASE_URL env var — Aaron's certified staging URL)
    tenant:      qa-smoke
    pub400_host: pub400.com
    test_suite:  ui_journey_p0_suite_command
    expected_tool_count: 12
    output_path: {fleet}/fleet-workspace/smoke-latest/lynn-report.json

Wait for Lynn to complete. Read lynn-report.json.

For each failure Lynn reports:
    - Apply Lynn's Step 5 ticket-filing rules (agents/lynn.md):
        code_bug   → compute dedup_hash, search open issues, comment
                     if dup, else create new issue with labels:
                     qa-bot, severity/Px, needs-fix, tool-bug
        env_problem → log in lynn-report only; NO ticket this routine
        flaky       → log in lynn-report only; NO ticket this routine
                     (env_problem and flaky belong to Routine 3)

STEP 4 — Degradation check.
Before filing individual tickets, apply these rules:

Rule A — mass failure:
    If >= 6 of 12 P0 tools failed in THIS run:
        → File ONE severity/P0 issue in RSA-Data-Solutions/iNova:
              title:  "P0 SUITE DEGRADATION — qa-smoke-hourly"
              labels: qa-bot, severity/P0, platform_failure
              body:   List all failing tools and their error summaries.
          Do NOT file individual per-tool tickets.

Rule B — repeat single-tool failure:
    Compare THIS run's failures against the previous hourly run's
    lynn-report.json (fleet-workspace/smoke-previous/lynn-report.json
    if it exists). If the same single P0 tool failed in BOTH runs:
        → File ONE severity/P0 issue in RSA-Data-Solutions/iNova:
              title:  "P0 SUITE DEGRADATION — qa-smoke-hourly"
              labels: qa-bot, severity/P0, tool-bug
              body:   Name the tool, paste both run timestamps and
                      error messages.
          Do NOT file individual tickets for that tool.

If neither rule triggers, proceed with per-tool ticket filing from
STEP 3 as normal.

STEP 5 — Sam: fix code_bug failures only.
If any code_bug tickets were filed (and no P0 SUITE DEGRADATION):

Spawn Sam (agents/sam.md) as a subagent for EACH independent code_bug.
Sam's scope this routine:
    - Fix ONLY failures classified as code_bug by Lynn
    - SKIP env_problem and flaky (they belong to Routine 3)
    - Attempt a fix; if scope exceeds budget, add needs-human-review
      and bow out (Sam's normal escalation path)

Collect Sam's fix reports.

STEP 6 — Push green build (if safe).
Conditions to push:
    - At least one fix was made AND tests re-pass after the fix
    - NO open severity/P0 tickets exist for the iNova or IBMiMCP repos
      (search via GitHub API: label=severity/P0 state=open)
    - No regressions introduced by Sam's changes

If conditions are met:
    git add <only the files Sam changed>
    git commit -m "fix: hourly smoke fixes [qa-smoke-hourly]"
    git push origin main

If any P0 ticket is open, DO NOT push — leave for human review.

STEP 7 — Archive and heartbeat.
1. Rotate reports:
   Copy fleet-workspace/smoke-latest/ → fleet-workspace/smoke-previous/
   (overwrite previous). This preserves the last run for Rule B above.

2. Write heartbeat:
   Overwrite fleet-workspace/heartbeats/qa-smoke-hourly.txt with:
       {current UTC ISO-8601 timestamp}
   Example: 2026-04-27T14:05:32Z
   The external watchdog reads this file; a missing or stale heartbeat
   signals a silent routine failure.

3. Commit and push:
   git add fleet-workspace/heartbeats/qa-smoke-hourly.txt \
           fleet-workspace/smoke-previous/ \
           fleet-workspace/smoke-latest/
   git commit -m "heartbeat: qa-smoke-hourly {timestamp}"
   git push origin main

Hard limits:
- Total run cap: 30 minutes
- Never log secrets (QA_TENANT_SMOKE_PASSWORD, tokens)
- Never force-push or skip hooks
- ALWAYS write the heartbeat, even if earlier steps failed
- Do NOT push app code if any severity/P0 ticket is open
```

## What this routine does and does not do

Doing:
- Deploys latest main via Aaron and certifies IBMiMCP health
- Runs all 12 P0 tools via the qa-smoke tenant against pub400.com
- Files individual tickets for code_bug failures (dedup-aware)
- Files a single P0 SUITE DEGRADATION ticket when mass-failure or
  repeat-failure thresholds are hit
- Has Sam auto-fix code_bug failures within scope budget
- Rotates reports so Rule B (repeat-failure detection) works across runs
- Writes a heartbeat file the external watchdog monitors

Not doing:
- Filing tickets for env_problem or flaky failures (Routine 3 handles those)
- Pushing app code when any P0 ticket is open
- Closing issues (Routine 4 post-deploy verifies and closes)
- Running after 23:05 or before 07:05 local time
- Running during pub400.com maintenance window

## Prerequisites before going live

1. Routine created in `claude.ai/code/routines` with the prompt above
2. Environment variables set in the routine settings panel:
       QA_BASE_URL
       QA_TENANT_SMOKE_PASSWORD
3. All repos attached:
       RSA-Data-Solutions/always-on-engineering-fleet
       RSA-Data-Solutions/iNova
       RSA-Data-Solutions/IBMiMCP
4. GitHub labels exist in iNova and IBMiMCP repos
   (see routines-final.md for the full `gh label create` block)
5. `fleet-workspace/heartbeats/qa-smoke-hourly.txt` initialised
   (done — committed alongside this file)
6. `fleet-workspace/smoke-latest/` and `fleet-workspace/smoke-previous/`
   directories will be created by the routine on first run

## Heartbeat watchdog note

The file `fleet-workspace/heartbeats/qa-smoke-hourly.txt` contains the
UTC timestamp of the last successful routine completion. An external
watchdog should alert if the timestamp is older than 2 hours (one missed
run + buffer). A missing file also counts as a silent failure.
