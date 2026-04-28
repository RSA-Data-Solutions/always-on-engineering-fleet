# Routine 1 — Hourly Smoke (`qa-smoke-hourly`)

This is the canonical definition for the `qa-smoke-hourly` routine.
It supersedes the Routine 1 entry in `routines-1-2-3.md`.

Key changes from the previous version:
- **Aaron deploy step added**: stack is deployed from latest main and
  IBMiMCP health is certified before Lynn runs any tests.
- **Sam is active**: fixes `code_bug` failures in-loop (up to 3 iterations).
  `env_problem` and `flaky` failures are ignored — they belong to Routine 3.
- **Push gate**: Ram never pushes while a `severity/P0` issue is open in iNova.
- **Consecutive-failure degradation**: a single P0 tool failing in TWO consecutive
  hourly runs triggers a suite-level `P0 SUITE DEGRADATION` issue instead of
  individual per-tool tickets.

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

Runs at :05 past every hour from 07:00 to 23:00 local time (17 runs/day).
Avoids the pub400 maintenance window (03:00–04:00 UTC).

---

## Ram agent parameters

| Parameter | Value |
|-----------|-------|
| `skill_path` | `SKILL.md` |
| `context_file` | `contexts/inova.md` |
| `max_iterations` | `3` |
| `enable_research` | `false` |

---

## Prompt

Paste the block below verbatim into the Claude.ai Routines prompt field.

```
You are the orchestrator (Ram) for an hourly P0 smoke run.
Aaron deploys first; Lynn tests against the certified build;
Sam fixes code_bug regressions. You play all three roles sequentially.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    - always-on-engineering-fleet  (fleet repo — your manual + workspace)
    - iNova                        (qa/ test suite lives here)
    - IBMiMCP                      (MCP server — Aaron deploys this)

STEP 1 — Read your manual.
Read these files before acting in any role:
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md

STEP 2 — Act as Aaron (deploy + health check).
Per agents/aaron.md, deploy the inovaide.com stack from the latest main
branch commit of both iNova and IBMiMCP:

    a) git -C {iNova}   pull origin main
       git -C {IBMiMCP} pull origin main

    b) Build and start the full stack using the start_command from
       contexts/inova.md.

    c) Verify IBMiMCP connection health:
           - Health endpoint responds HTTP 200
           - registered_tool_count >= 130

    d) Record the result in a JSON object (do not write to disk, hold
       in memory):
           {
             "timestamp": "<UTC ISO>",
             "iNova_sha": "<git rev-parse HEAD in iNova>",
             "IBMiMCP_sha": "<git rev-parse HEAD in IBMiMCP>",
             "overall_status": "READY" | "FAILED",
             "registered_tool_count": <int>,
             "notes": "<any error messages>"
           }

If overall_status = FAILED:
    1. Compute dedup_hash = sha256("aaron-deploy-failed" + date_utc[:10])[:12]
       Search open issues in RSA-Data-Solutions/iNova for
       "Dedup hash: {dedup_hash}".
         Found open issue  → comment "Aaron deploy failed again at
                             {timestamp}. Details: {notes}" and stop.
         No open issue     → file ONE new issue:
               Title:  "Aaron deploy failed"
               Labels: qa-bot, platform_failure, severity/P0
               Body:   Include timestamp, iNova_sha, IBMiMCP_sha,
                       registered_tool_count, error notes, and
                       "Dedup hash: {dedup_hash}" on its own line.
    2. Write the RED heartbeat (see STEP 5 format).
    3. STOP. Do not run QA against a broken build.

STEP 3 — Act as Lynn (QA).
Only runs when Aaron reported READY.
Per agents/lynn.md, run the P0 suite against the Aaron-certified server:

    cd {iNova}/qa
    python3 -m venv .venv 2>/dev/null || true
    source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium

    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

This exercises all 12 P0 tools via the qa-smoke tenant against pub400.com.

── Degradation check (evaluate BEFORE filing any individual tickets) ──

Read the last line of:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
to obtain previous_failing_tools (may be empty on first run).

Condition A: >= 6 of the 12 P0 tools fail in this run.
Condition B: any single tool that appears in both this run's failures
             AND previous_failing_tools.

If Condition A OR Condition B is true:
    - Collect the full failing_tools list (all tools that failed this run).
    - Compute dedup_hash = sha256("p0-degradation" + date_utc[:10])[:12]
    - Search open issues in RSA-Data-Solutions/iNova for
      "Dedup hash: {dedup_hash}".
        Found → comment "P0 suite still degraded at {timestamp}.
                Failing tools: {failing_tools}" and skip to STEP 5.
        Not found → file ONE issue:
              Title:  "P0 SUITE DEGRADATION"
              Labels: qa-bot, severity/P0, platform_failure
              Body:   Failing tool list, run timestamp, pub400
                      connection status, Aaron deploy SHAs, and
                      "Dedup hash: {dedup_hash}" on its own line.
    - Skip STEP 4 entirely (systemic degradation needs human triage,
      not an automated code fix).
    - Go directly to STEP 5.

── Per-failure ticket filing (only when no degradation) ──

For each failure in /tmp/p0-report.json:

    failure_type = "code_bug":
        Apply Lynn's Step 5 ticket-filing rules (lynn.md).
        Compute:
            dedup_hash = sha256(repo + test_name + first_line(error)
                                + tool_name)[:12]
        Search open issues in the target repo for
        "Dedup hash: {dedup_hash}".
            Found  → comment "Reoccurred at {timestamp} in hourly smoke."
            Not found → create issue per lynn.md schema with labels:
                        qa-bot, severity/Px, needs-fix

    failure_type = "env_problem" or "flaky":
        Log in /tmp/p0-report.json but do NOT file a ticket and do NOT
        pass to Sam. These belong to Routine 3.

STEP 4 — Act as Sam (SE fix loop). Max iterations: 3.
Only runs when no degradation was triggered and there are code_bug
failures to address.

For each code_bug failure from Lynn's report:
    - Read the failing test and error message.
    - Locate the root cause in the source code (use grep/read, do not guess).
    - Make the smallest change that resolves the failure.
    - Re-run the specific failing test — must pass before proceeding.
    - Run adjacent tests to confirm no regressions.

After all fixes are applied, run the full P0 suite once more to confirm
the overall suite is green. If the same test still fails after 3 attempts:
    - Add label needs-human-review to its ticket.
    - Comment: "Sam-bot exhausted 3 fix attempts on this routine run.
                Escalating to human review."
    - Do not block the push on this test; treat it as unresolved.

Push gate:
    After Sam completes, check for open severity/P0 issues in
    RSA-Data-Solutions/iNova (state: open, label: severity/P0).
        Any P0 open → do NOT push Sam's fixes. Stage the commit but
                      hold. Write to fleet-workspace/summary.md:
                      "Fix committed but not pushed — P0 ticket open
                       at {timestamp}."
        No P0 open  → Ram pushes normally:
                          git add <only files Sam changed>
                          git commit -m "fix: <summary> [qa-smoke-hourly]"
                          git push origin main

STEP 5 — Heartbeat.
Append ONE line to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt

Line format (all on one line, no wrapping):
    {UTC_ISO_TIMESTAMP} status={GREEN|AMBER|RED} p0_pass={N}/12 failing_tools={comma-list|NONE} iNova_sha={sha8} IBMiMCP_sha={sha8}

    GREEN  = all 12 tools pass
    AMBER  = 1-5 code_bug failures, no degradation, Sam attempted fixes
    RED    = degradation triggered OR Aaron FAILED OR timeout

The failing_tools field is read by the NEXT hourly run to evaluate
Condition B (consecutive single-tool failure). Always populate it
accurately — NONE if zero failures.

Commit and push to the fleet repo main branch:
    git add {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
    git commit -m "heartbeat: qa-smoke-hourly {UTC_ISO_TIMESTAMP}"
    git push origin main

Always write and push the heartbeat — even if the run ended early
(Aaron FAILED, timeout, etc.). A missing heartbeat signals a silent
routine failure to the external watchdog.

Hard limits:
- Total run time cap: 25 minutes. If exceeded: write RED heartbeat
  with note "timed out at STEP {N}" and stop immediately.
- Never commit secrets, passwords, or QA bypass tokens.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
- Never push to iNova main while any severity/P0 issue is open.
- Never push directly to a protected branch without the push gate check.
```

---

## Environment variables required

Set these in the routine's settings panel — never in the prompt text:

| Variable | Purpose |
|----------|---------|
| `QA_BASE_URL` | Aaron-deployed local staging URL |
| `QA_TENANT_SMOKE_PASSWORD` | Password for qa-smoke@inovaide-qa.com |

---

## Cap accounting

```
qa-smoke-hourly:   17 runs/day  (07:05–23:05 local, one per hour)
% of Team plan:    68%  (17/25)
```

Leaves 8 slots/day for Routines 4 and 5 (webhook-driven).

---

## Heartbeat watchdog expectations

| Field | Value |
|-------|-------|
| Path | `fleet-workspace/heartbeats/qa-smoke-hourly.txt` |
| Frequency | Every hour, 07:05–23:05 local |
| Acceptable gap | ≤ 2 hours (one missed beat tolerated; two consecutive = alert) |
| Content | One line per run: timestamp, status, p0_pass count, failing_tools |

The `failing_tools` field on each heartbeat line is the mechanism for
Condition B (consecutive single-tool failure) in the degradation rule.
Do not omit it.
