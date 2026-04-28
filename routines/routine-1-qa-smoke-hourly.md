# Routine 1 — Hourly Smoke (P0 suite + deploy)

**Routine name:** `qa-smoke-hourly`  
**Version:** 2 (Aaron-gated deploy + Sam fix loop)  
**Supersedes:** `qa-smoke-hourly` v1 (live-site-only) described in `routines-1-2-3.md`

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

Runs at :05 past every hour from **07:05 to 23:05** local time.  
17 runs per day. Avoids the pub400 maintenance window (03:00–04:00 UTC).

If the routines UI does not accept a range for the hour field, expand it:

```
5 7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 * * *
```

---

## Repos required (attach all three to the routine)

- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

GitHub connector needs **issues:write** + PR read/write on all three.

---

## Environment variables (set in routine's env panel, NOT in the prompt)

```
QA_BASE_URL                 = https://inovaide.com
QA_BYPASS_SECRET            = <hmac secret from iNova .env>
QA_TENANT_SMOKE_PASSWORD    = <qa-smoke@inovaide-qa.com password>
```

---

## What makes this version different from v1

| Aspect | v1 (routines-1-2-3.md) | v2 (this file) |
|--------|------------------------|----------------|
| Server under test | Live inovaide.com (no deploy) | Aaron deploys local staging from latest `main` |
| IBMiMCP health gate | None | `registered_tool_count ≥ 130`; FAILED → file ticket + stop |
| Sam role | Read-only triage | Fixes `code_bug` failures in-loop |
| env_problem / flaky | Filed if found | Ignored; routed to Routine 3 |
| Push guard | Not specified | Ram blocks push if any P0 ticket is open |

---

## Prompt

Paste the block below into the routine's prompt field:

```
You are the orchestrator (Ram) for an hourly P0 smoke run that includes
a fresh deploy of the inovaide.com stack.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    - always-on-engineering-fleet  (fleet repo — your operating manual)
    - iNova                        (qa/ test suite)
    - IBMiMCP                      (tool inventory reference)

STEP 1 — Read your manual.
Read (use absolute paths):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You will play Ram, Aaron, Lynn, and Sam sequentially in this session.

STEP 2 — Act as Aaron (deploy).
Per agents/aaron.md, deploy the inovaide.com stack from the latest
commit on main:

    cd {iNova}
    git fetch origin main && git checkout main && git pull
    docker compose -f docker-compose.dev.yml build --no-cache
    docker compose -f docker-compose.dev.yml up -d
    # wait for health check to pass (poll /health every 5 s, timeout 120 s)

Verify IBMiMCP connection:
    - Call the MCP server's /tools/list endpoint (or equivalent)
    - Assert registered_tool_count ≥ 130

If the deploy fails OR registered_tool_count < 130:
    - Classify as platform_failure
    - File ONE issue in RSA-Data-Solutions/iNova:
        title:  "Aaron deploy failed"
        labels: qa-bot, platform-bug, severity/P0, auto-filed
        body:   include docker build/compose logs, tool count observed,
                and current UTC timestamp
    - Append to heartbeat (Step 5) with outcome=FAILED_AARON_GATE
    - STOP — do NOT proceed to Lynn; do not run QA against a broken build.

If deploy succeeds and tool count ≥ 130: continue to Step 3.

STEP 3 — Act as Lynn (QA).
Run the P0 suite against the Aaron-certified server:

    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=http://localhost:<port_aaron_started_on> \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

For each failure in /tmp/p0-report.json:

    failure_type == "code_bug":
        Apply Lynn's Step 5 ticket-filing rules (lynn.md).
        Compute: dedup_hash = sha256(target_repo + test_name +
                              first_line(error) + tool_name)[:12]
        Search open issues in target_repo for "Dedup hash: {hash}".
        If found: add comment "Reoccurred at {now} on qa-smoke-hourly."
        If not:   create issue per lynn.md schema.
                  labels: qa-bot, severity/Px, needs-fix

    failure_type == "env_problem" or "flaky":
        Skip ticket creation. Note in qa-report only.
        These belong to Routine 3.

Degradation rule (check AFTER processing all failures):
    Condition A: ≥ 6 of the 12 P0 tools failed in this single run.
    Condition B: The same single P0 tool failed in this AND the previous
                 hourly run (check fleet-workspace/heartbeats/qa-smoke-hourly.txt
                 for the prior run's failing_tools list).
    If Condition A OR Condition B is true:
        - Close (or skip filing) any individual tickets for this run.
        - File ONE severity/P0 issue in RSA-Data-Solutions/iNova:
              title:  "P0 SUITE DEGRADATION"
              labels: qa-bot, severity/P0, auto-filed
              body:   list every failing tool name, run timestamp, and
                      which condition triggered this (A / B / both).

STEP 4 — Act as Sam (SE).
For each code_bug failure Lynn identified (and for which a ticket was
filed or already exists):

    Per agents/sam.md:
    - Read the failing test and the relevant source files.
    - Form a hypothesis. Make the smallest change that fixes the test.
    - Re-run the failing test — must pass.
    - Re-run adjacent tests — must still pass.
    - Run linters per the repo's CI config.

    DO NOT attempt to fix:
        - env_problem failures   → Routine 3 handles these
        - flaky failures         → Routine 3 handles these
        - P0 SUITE DEGRADATION   → requires human review

    If Sam cannot reproduce or scope exceeds 5 files / 100 lines:
        Comment on the issue: "Sam-bot: cannot auto-fix; needs human review."
        Add label: needs-human-review
        Remove label: needs-fix
        Skip that bug and continue.

STEP 5 — Push decision (Ram).
If Sam fixed one or more bugs AND all P0 tests now pass AND no P0
ticket is currently open:
    git add <only files changed by Sam>
    git commit -m "fix(<area>): <summary> [qa-smoke-hourly auto-fix]"
    git push origin main

If ANY P0 ticket is open (including ones just filed this run):
    DO NOT push. Log reason in heartbeat.

STEP 6 — Heartbeat.
Append the following record to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt

    {ISO_UTC_timestamp}
    routine=1 outcome={GREEN|FAILED_AARON_GATE|P0_OPEN|DEGRADATION}
    p0_pass={N} p0_fail={N} p0_total=12
    failing_tools={comma-separated tool names, or NONE}
    tickets_filed={N} fixes_pushed={N}

Commit with message "heartbeat: qa-smoke-hourly {timestamp}" and push
to the fleet repo's main branch.

Hard limits:
- Total run time cap: 20 minutes. If exceeded, file ONE severity/P1
  issue "Routine 1 timed out at {step}" in iNova repo, write heartbeat
  with outcome=TIMEOUT, and stop.
- Never commit secrets, passwords, or QA bypass tokens.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
- Never force-push or skip git hooks.
- Never push directly to main if any P0 issue is open.
```

---

## Cap accounting

```
R1 hourly smoke   17 runs/day  (68% of 25-run Team plan)
R2 signup daily    1 run/day   (4%)
R3 explore daily   1 run/day   (4%)
R4 post-deploy     webhook     (variable)
R5 fix-on-issue    webhook     (variable)
                  ──────────────
total scheduled   19 runs/day  (76%)
```

Team plan (25/day) is the floor. Enable metered overage for heavy fix days.

---

## Rollout note

Enable **after** Routine 4 is verified stable (Aaron deploy step is shared
logic — if Aaron is broken, R1 v2 and R4 will both catch it via the FAILED
gate, giving two signal sources instead of one).
