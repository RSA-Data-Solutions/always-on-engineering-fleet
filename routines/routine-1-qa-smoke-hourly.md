# Routine 1 — Hourly Smoke (P0 Suite + Aaron Deploy)

## Metadata

| Field | Value |
|-------|-------|
| Name | `qa-smoke-hourly` |
| Schedule | `5 7-23 * * *` UTC |
| Runs | 17/day — :05 past each hour, 07:00–23:00 UTC |
| Maintenance skip | 03:00–04:00 UTC (pub400) — already excluded by hour range |
| Target | Aaron-deployed local staging (not live inovaide.com) |
| Agent | Ram (`agents/ram.md`) |
| `max_iterations` | 3 |
| `enable_research` | false |
| `context_file` | `contexts/inova.md` |
| `skill_path` | `SKILL.md` |

---

## Purpose

Every hour during working hours, this routine:

1. **Aaron** deploys the full iNova stack from latest `main` and verifies the IBMiMCP
   server is healthy with `registered_tool_count ≥ 130`. If Aaron fails, one
   `platform_failure` ticket is filed and the run stops — QA never runs against a
   broken build.
2. **Lynn** runs all 12 P0 tools via the `qa-smoke` tenant against pub400.com on the
   Aaron-certified staging server.
3. **Sam** fixes any `code_bug` failures (up to 2 bugs per run, ≤40 min total).
   `env_problem` and `flaky` failures are silently logged — they are owned by Routine 3.
4. **Ram** pushes green fixes, but only when no `severity/P0` `qa-bot` issue is open.
5. A heartbeat line is appended to `fleet-workspace/heartbeats/qa-smoke-hourly.txt`
   so the external watchdog can detect silent failures.

---

## Required setup

### Repos attached
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

### GitHub connector
Requires `issues:write` + PR write access on all three repos.

### Environment variables (set in routine settings panel — never in the prompt)

| Variable | Description |
|----------|-------------|
| `QA_TENANT_SMOKE_PASSWORD` | Password for `qa-smoke@inovaide-qa.com` |
| `IBMIMCP_ADMIN_API_KEY` | IBMiMCP admin API key (for Aaron's `tools/list` health check) |
| `IBMIMCP_URL` | IBMiMCP local URL, e.g. `http://localhost:3051` |
| `INOVA_STAGING_URL` | Base URL for Aaron-deployed iNova frontend, e.g. `http://localhost:3000` |

> `QA_BASE_URL` is intentionally absent — Lynn targets `$INOVA_STAGING_URL`,
> not the live inovaide.com site.

---

## Cap accounting

```
qa-smoke-hourly    17 runs/day  (68% of 25/day Team plan)
qa-signup-daily     1 run/day   (4%)
qa-explore-daily    1 run/day   (4%)
qa-release (R4)     webhook     (variable)
                   ──────────
scheduled total:   19 runs/day  (76%)
```

6 runs/day headroom reserved for Routine 4 post-deploy webhook fires.

---

## Watchdog contract

The routine appends one line to `fleet-workspace/heartbeats/qa-smoke-hourly.txt`
every run. The external watchdog reads this file; a missing or stale beat
(>70 minutes between entries) signals a silent routine failure.

**Watchdog alarm threshold: 70 minutes** (60-minute schedule + 10 minutes of
cron/startup drift tolerance).

Heartbeat line format:
```
{ISO-UTC-timestamp} | passed={N} failed={N} code_bug={N} env={N} flaky={N} fixed={N} pushed={sha|none} p0_open={true|false} | failing_tools={tool1,tool2|none}
```

The `failing_tools` field is used by the NEXT run for consecutive-failure degradation
detection (Condition B of the degradation rule in STEP 3).

---

## Prompt

Paste the block below verbatim into the routine's prompt field in `claude.ai/code/routines`.

```
You are the orchestrator (Ram) for an hourly P0 smoke run against Aaron-deployed
local staging. No webhook payload — this is a scheduled run.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    - always-on-engineering-fleet  (your operating manual)
    - iNova                        (qa/ test suite, source code)
    - IBMiMCP                      (tool inventory reference)

STEP 1 — Read your manual.
Read these files using absolute paths:
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/aaron.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You will play Ram, Aaron, Lynn, and Sam roles sequentially in this session.

STEP 2 — Act as Aaron (deploy + verify). Time budget: 10 minutes.
Per agents/aaron.md, deploy the iNova stack from latest main.

    a) Pull latest main in {iNova}:
           cd {iNova} && git fetch origin main && git checkout main && git pull origin main

    b) Pull latest main in {IBMiMCP}:
           cd {IBMiMCP} && git fetch origin main && git checkout main && git pull origin main

    c) Tear down any stale stack and bring up fresh:
           cd {iNova}
           docker compose -f docker-compose.dev.yml down --remove-orphans || true
           docker compose -f docker-compose.dev.yml up -d --build
           sleep 10

    d) Health-check the iNova orchestrator:
           curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health
       Accept HTTP 200 or 404 as "up". Anything else (connection refused,
       5xx) is FAILED.

    e) Verify IBMiMCP is connected — query tools/list and count registered tools:
           curl -s -X POST ${IBMIMCP_URL:-http://localhost:3051}/mcp \
             -H "Content-Type: application/json" \
             -H "x-api-key: $IBMIMCP_ADMIN_API_KEY" \
             -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
       Parse the JSON response; count the length of the "tools" array.
       Capture as registered_tool_count.

    f) Evaluate Aaron's result:
       - If docker compose failed
         OR iNova health check returned anything other than 200/404
         OR registered_tool_count < 130:

             File ONE issue in RSA-Data-Solutions/iNova:
                 title:  "Aaron deploy failed — qa-smoke-hourly {UTC timestamp}"
                 body:   "Aaron reported FAILED during hourly smoke setup.\n\n"
                         "registered_tool_count={count}\n"
                         "iNova health status={http_status}\n\n"
                         "Session: {session_url}"
                 labels: qa-bot, platform-bug, severity/P0, auto-filed

             Write the heartbeat (STEP 5) with:
                 passed=0 failed=0 code_bug=0 env=0 flaky=0 fixed=0
                 pushed=none p0_open=true failing_tools=none
                 (append a note: "STOPPED — Aaron deploy failed")
             Then STOP. Do not proceed to QA against a broken build.

       - If all checks pass: note staging base URL as
             ${INOVA_STAGING_URL:-http://localhost:3000}
         and continue to STEP 3.

STEP 3 — Act as Lynn (QA). Time budget: 15 minutes.
Per agents/lynn.md, run the P0 suite against the Aaron-certified staging server.
This exercises all 12 P0 tools via the qa-smoke tenant against pub400.com.

    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=${INOVA_STAGING_URL:-http://localhost:3000} \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

Read /tmp/p0-report.json. Classify each failure per lynn.md Step 3:
    code_bug    → queue for Sam in STEP 4
    env_problem → log in heartbeat ONLY; do NOT file a ticket (Routine 3 owns these)
    flaky       → log in heartbeat ONLY; do NOT file a ticket (Routine 3 owns these)
    unknown     → treat as code_bug conservatively

For each code_bug — apply lynn.md Step 5 ticket-filing rules UNLESS the degradation
rule below triggers first:
    - Compute dedup_hash = sha256(target_repo + test_name + first_line(error) + tool_name)[:12]
    - Search open issues in the target repo for "Dedup hash: {hash}"
    - If found: add comment "Reoccurred at {timestamp} on qa-smoke-hourly."
    - If not: create issue per lynn.md schema with labels:
          qa-bot, severity/Px, needs-fix, auto-filed

DEGRADATION RULE — evaluate BEFORE filing individual tickets:
    Condition A: ≥6 of 12 P0 tools fail in THIS run.
    Condition B: The SAME single P0 tool that failed now also appears in the
                 `failing_tools` field of the most recent line in
                 {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
                 (i.e., it failed in the previous hourly run too).

    If EITHER condition is met:
        - Open ONE issue in RSA-Data-Solutions/iNova:
              title:  "P0 SUITE DEGRADATION — {UTC timestamp}"
              body:   "Degradation threshold triggered on qa-smoke-hourly.\n\n"
                      "Condition met: {A: ≥6 tools | B: {tool_name} failed twice consecutively}\n"
                      "Failing tools: {comma-separated list}\n\n"
                      "Session: {session_url}"
              labels: qa-bot, severity/P0, auto-filed
        - Do NOT file individual per-tool tickets.
        - Skip STEP 4 (Sam fixes). Do not push against a degraded suite.
        - Go directly to STEP 5.

STEP 4 — Act as Sam (SE). Time budget: 10 minutes per bug; max 2 bugs this routine.
For each code_bug failure queued from STEP 3 (in order of severity, highest first):

    Per agents/sam.md:
    a) Read the failing test body to understand the assertion and root cause.
    b) Search related source files (grep, do not guess).
    c) Write the minimal fix: ≤5 files, ≤100 lines total.
    d) Retest the specific failing test:
           QA_HEADLESS=true \
           QA_BASE_URL=${INOVA_STAGING_URL:-http://localhost:3000} \
           QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
             python -m pytest ui_journey/test_p0_suite.py::test_{name} -v
       Must pass before continuing.
    e) Run the rest of the P0 suite to verify no regressions:
           python -m pytest ui_journey/test_p0_suite.py -v \
             --json-report --json-report-file=/tmp/retest-report.json
    f) Run linters as defined in {iNova}/.github/workflows/.

    If Sam cannot fix within budget (scope too large, cannot reproduce, linter fails):
        - Add label `needs-human-review` to the issue; remove `needs-fix`
        - Comment: "Sam-bot: fix scope exceeded budget on qa-smoke-hourly. Needs human review."
        - Move on to the next bug (if any remain in the 2-bug budget).

    Hard stops for Sam:
    - NEVER touch CI/CD pipelines, secrets, or auth code unless the issue carries
      `auth-touch-allowed` (a human-applied label).
    - NEVER push directly to main — fixes stay staged until Ram's push authority check below.

PUSH AUTHORITY CHECK (Ram, after Sam finishes):
    Check for open issues in RSA-Data-Solutions/iNova with BOTH labels:
        qa-bot AND severity/P0
    - If ANY such issue is open: do NOT push. Log "push blocked: open P0 ticket(s)" in heartbeat.
    - If none open AND Sam made at least one fix:
          git -C {iNova} add <only files changed by Sam>
          git -C {iNova} commit -m "fix: {summary} [qa-smoke-hourly {timestamp}]"
          git -C {iNova} push origin main
      Capture the commit SHA for the heartbeat.
    - If Sam made no fixes: skip push.

STEP 5 — Heartbeat.
Read the last line of {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt (if it
exists) to confirm you can write to it. Then APPEND one new line:

    {ISO-UTC-timestamp} | passed={N} failed={N} code_bug={N} env={N} flaky={N} fixed={N} pushed={sha|none} p0_open={true|false} | failing_tools={tool1,tool2|none}

Example:
    2026-04-28T08:05:44Z | passed=11 failed=1 code_bug=1 env=0 flaky=0 fixed=1 pushed=abc1234 p0_open=false | failing_tools=none

Commit and push to the fleet repo:
    git -C {fleet} add fleet-workspace/heartbeats/qa-smoke-hourly.txt
    git -C {fleet} commit -m "heartbeat: qa-smoke-hourly {timestamp}"
    git -C {fleet} push origin main

Hard limits (all steps):
- Total wall-clock cap: 40 minutes. If exceeded at any step, write a partial heartbeat
  "TIMEOUT at STEP {N}" and stop.
- Never commit secrets, passwords, or QA bypass tokens.
- Never push Sam's fixes to main if any severity/P0 qa-bot issue is open.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
- env_problem and flaky failures are silent in this routine — no tickets, no fixes.
- Max 2 Sam fix attempts per run to stay within the 40-minute cap.
```
