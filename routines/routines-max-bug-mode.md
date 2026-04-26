# Maximum-Bug-Finding Routines

Reorganized routine plan for the goal: find as many bugs as possible
within the 15/day cap, with autonomous fixes via Sam-bot.

## What changed from the previous plan

Old: 11 hourly smoke runs + 1 signup + 1 explore = 13/day, leaves 2
for fix cycles. Smoke runs find nothing new on runs 2-11.

New: 0 smoke runs on Routines (moved to homelab cron, unlimited).
Three differentiated exploration routines spread across the day +
1 signup + 1 chaos = 5/day scheduled, leaves 10/day for fix-and-retest.

This delivers ~3-4x more bug-finding throughput from the same cap.

## Cap allocation under maximum-bug mode

```
Tier 1 — Homelab cron (free, unlimited):
  Smoke every 15 min                      ~64 runs/day
  Health check every 5 min                ~288 runs/day
  Total                                   ~350 runs/day, $0

Tier 2 — Routines (15/day cap):
  R-explore-morning   06:00 CT            1
  R-explore-midday    12:00 CT            1
  R-explore-evening   18:00 CT            1
  R-signup-fresh      02:00 CT            1
  R-chaos             09:00 CT            1
                                         ───
  Scheduled total                          5/day  (33% of cap)

  Reserve for:
  R4 post-deploy webhook                  ~2-5/day
  R5 Sam-bot autofix webhook              ~3-7/day
                                         ───
  Total expected                          10-12/day  safe under 15
```

## The five Routines, each with a DIFFERENT angle

The key insight: each routine must hunt for a *different class of bug*.
Three identical "explore" routines just waste runs. These are
differentiated.

---

## Routine A — Morning Exploration (Dhira + tool inventory diff)

### Schedule: `0 11 * * *` UTC (06:00 CT)

### Hunting target: tools added/changed since yesterday

### Prompt

```
You are the orchestrator for morning exploratory QA. Today's hunt:
test what's NEW. Tools added or modified in IBMiMCP since yesterday
are the most likely place for fresh bugs.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify paths to: always-on-engineering-fleet, iNova, IBMiMCP.

STEP 1 — Read manual.
{fleet}/SKILL.md, {fleet}/agents/ram.md, {fleet}/agents/dhira.md,
{fleet}/agents/lynn.md, {fleet}/contexts/inova.md,
{fleet}/contexts/ibmimcp.md.

STEP 2 — Dhira: identify "new" surface area.
    cd {IBMiMCP}
    git log --since="24 hours ago" --name-only --pretty=format: \
        -- src/tools/ | sort -u | grep -v '^$' > /tmp/changed-tools.txt
    cat /tmp/changed-tools.txt

If empty, expand window: --since="72 hours ago".
If still empty, today's hunt pivots to the lowest-coverage tool from
contexts/inova.md rotation_batches (any tool from this week's batch
that has zero entries in /tmp/regression-report.json from the last
3 days).

For each changed tool file:
    - Read the source to understand what changed
    - Read its inputSchema
    - Generate 5 test inputs:
        1. Happy path with golden values
        2. Happy path with edge values (max length, max int, etc.)
        3. Required field missing
        4. Type mismatch (string where int expected)
        5. Realistic-but-pathological (Unicode, embedded quotes,
           timestamps near DST boundaries, etc.)

STEP 3 — Lynn: invoke each input, observe.
    cd {iNova}/qa
    source .venv/bin/activate || (python3 -m venv .venv && \
        source .venv/bin/activate && pip install -q -r requirements.txt && \
        playwright install --with-deps chromium)

For each (tool, input) tuple, invoke via OpenCode and capture:
    - success: true/false
    - response shape vs expected
    - latency_ms
    - any error message text (look for stack traces leaking,
      inconsistent error codes, Unicode mangling)

STEP 4 — File issues for any anomaly.
File a separate issue per anomaly using Lynn's standard schema and
labels qa-bot, needs-fix, severity/Px, tool-bug, routine-explore-morning.
Severity:
    - Stack trace leaking to user → P0
    - Tool succeeded on malformed input → P1 (silent corruption risk)
    - Wrong error code for known error case → P2
    - Inconsistent shape between similar tools → P2
    - Slow response (>2x peer tools) → P3 (no needs-fix label, P3
      doesn't trigger Sam)

STEP 5 — Heartbeat.
{fleet}/fleet-workspace/heartbeats/r-explore-morning.txt

Hard limits:
- Run cap: 25 minutes
- Max 4 issues filed per run (4 per routine × 3 routines × 1 chaos
  = 16 max issues/day, comfortably below Sam's 7-fix budget)
- Do NOT touch baseline_metrics.json
```

---

## Routine B — Midday Exploration (real-tenant workflow simulation)

### Schedule: `0 17 * * *` UTC (12:00 CT)

### Hunting target: multi-step workflows that real tenants run

### Prompt

```
You are the orchestrator for midday QA. Today's hunt: realistic
multi-step workflows that mirror real tenant use cases. Most P0 tools
work in isolation but break in chains.

STEP 0-1 — Standard discovery + manual reading (see Routine A).

STEP 2 — Lynn: run workflow chains.
Pick ONE workflow per run, rotating daily:

  Monday    — "Inventory query": listTables(MSASHI1) → describeTable(picked) →
              runSQL(SELECT * FROM picked LIMIT 10) → assert column types match
              describe output.
  Tuesday   — "Source navigation": listSourceMembers(MSASHI1) →
              getSourceMember(picked) → assert content non-empty,
              CCSID metadata present.
  Wednesday — "Job inspection": listActiveJobs(QINTER) → getJobLog(picked) →
              assert messages array, timestamps in expected timezone.
  Thursday  — "IFS roundtrip": writeIFSFile(/tmp/qa-{ts}.txt, "test") →
              readIFSFile(same path) → assert content matches →
              listIFSDirectory(/tmp) → assert file appears.
  Friday    — "SQL multi-statement": runSQLScript with 3 chained CTEs
              against a real table, assert final shape.
  Saturday  — "Cross-tool consistency": getUserProfile(MSASHI) compared
              to listObjects(MSASHI1) ownership field — same user?
  Sunday    — "Concurrent sessions": open 2 OpenCode sessions, run same
              tool concurrently, assert no session bleed.

For each step in the chain:
    - Time it
    - Capture full response
    - Assert next step's input matches previous step's output

STEP 3 — File issues for chain breakage.
A chain failure is HIGH SIGNAL — these are the bugs that bite real
tenants. File with severity bumped one level vs. single-tool failure:
    - Chain breaks at any step → severity/P0 (was P1)
    - Data inconsistency between steps → severity/P0
    - Latency >threshold → severity/P1
Labels: qa-bot, needs-fix, severity/Px, routine-explore-midday,
plus tool-bug or platform-bug per Lynn rules.

STEP 4 — Heartbeat.
{fleet}/fleet-workspace/heartbeats/r-explore-midday.txt

Hard limits: same as Routine A.
```

---

## Routine C — Evening Exploration (cross-tenant boundary testing)

### Schedule: `0 23 * * *` UTC (18:00 CT)

### Hunting target: tenant isolation and security boundaries

### Prompt

```
You are the orchestrator for evening QA. Today's hunt: tenant
isolation. inovaide.com is multi-tenant — bugs here are SEVERE
because they leak across customers.

STEP 0-1 — Standard discovery + manual reading.

STEP 2 — Lynn: cross-tenant probes.
Use TWO QA tenants this run:
    - qa-smoke@inovaide-qa.com (tenant A)
    - qa-explore@inovaide-qa.com (tenant B)

For each probe, log in as tenant A, perform action, log out, log in
as tenant B, attempt to observe A's artefacts:

  Probe 1 — Session isolation:
    A logs in, gets session token. B logs in. Does B's OpenCode have
    A's recent tool history visible? (It shouldn't — but test it.)

  Probe 2 — IFS path traversal:
    A writes to /home/qa-A/test.txt. B attempts readIFSFile on
    A's home dir. Should fail with permission error, not silently
    return empty/null.

  Probe 3 — SQL schema visibility:
    A creates a temp table in their schema. B runs listTables on A's
    schema. Should fail or return empty, never return A's tables.

  Probe 4 — Job log visibility:
    A's user submits a job. B calls getJobLog on A's job ID.
    Should fail with permission error.

  Probe 5 — Source member access:
    A places a member in their library. B calls getSourceMember on
    A's library. Should fail with permission error.

  Probe 6 — Connection pool bleed:
    A closes session. B opens immediately. Does B's first tool call
    show any artefact from A's last call? (cached query plans, stale
    timestamps, etc.)

STEP 3 — File issues. Tenant isolation breakage = ALWAYS severity/P0.
Label any cross-tenant leak with: qa-bot, needs-fix, severity/P0,
security, tenant-isolation, routine-explore-evening.

CRITICAL: do NOT include any actual leaked data in the issue body.
Describe the leak abstractly: "Tenant B was able to observe tenant
A's <category>" — never paste the leaked content.

STEP 4 — Heartbeat.
{fleet}/fleet-workspace/heartbeats/r-explore-evening.txt

Hard limits: same as Routine A. Tenant isolation runs are pure
read-attempts — Lynn never modifies state.
```

---

## Routine D — Daily Signup (UNCHANGED from existing plan)

Schedule, prompt, repos: keep your existing Routine 2 spec. This is
already exactly the right shape.

---

## Routine E — Chaos Engineering

### Schedule: `0 14 * * *` UTC (09:00 CT)

### Hunting target: bizarre inputs and unusual sequences

### Prompt

```
You are the orchestrator for daily chaos. Today's hunt: bugs hiding
behind input the developers didn't think to test.

STEP 0-1 — Standard discovery + manual reading.

STEP 2 — Lynn: chaos inputs against P0 tools.
Pick 4 P0 tools at random from contexts/inova.md → P0 Tool Suite.
For each tool, generate 3 chaos inputs:

  - SQL: queries with intentional encoding mismatches (UTF-8 vs CCSID 273),
         empty strings, very long literals (>32K), Unicode in identifiers,
         comments injected mid-keyword, expressions that evaluate to NULL
         in unusual ways
  - Path: paths with .., paths starting with /, paths with embedded
          NUL bytes (encoded as \\u0000), Windows-style backslashes,
          paths longer than 255 chars
  - Identifier: names with all special chars, leading/trailing spaces,
                names that are SQL reserved words, lowercase variants of
                case-sensitive identifiers
  - Number: -1 where positive expected, MAX_SAFE_INTEGER, 0.5 where int
            expected, scientific notation, hex literals
  - Time: timestamps from year 9999, year 0001, leap second 23:59:60,
          DST transition moments, negative durations

Crucially: do NOT include inputs that would corrupt actual IBM i state
(no DROP TABLE, no DELETE, no overwrite of real files). These are READ
chaos inputs only.

STEP 3 — File issues for surprising responses.
"Surprising" includes:
    - Stack trace returned to client (always severity/P0)
    - Tool returned success:true on garbage input (severity/P1)
    - Tool returned success:false but with no error message (severity/P2)
    - Different error messages for the same logical error class (severity/P3)
    - Hangs > 30s on bounded input (severity/P1, possible DoS)
Labels: qa-bot, needs-fix, severity/Px, routine-chaos, tool-bug.

STEP 4 — Heartbeat.
{fleet}/fleet-workspace/heartbeats/r-chaos.txt

Hard limits:
- Run cap: 30 minutes
- Max 5 issues per run
- Inputs are READ-ONLY — never invoke a tool that mutates state
```

---

## How this maximises bug-finding throughput

Each routine has a non-overlapping hunting target:

```
A morning   — what changed? (regression hunting)
B midday    — what chains? (workflow hunting)
C evening   — what leaks? (security hunting)
D signup    — what onboards? (UX hunting)
E chaos     — what surprises? (robustness hunting)
```

Plus homelab smoke runs every 15 min hammering known surface area.

If Lynn finds 2-3 bugs per exploration run × 5 runs/day = 10-15 bugs
per day discovered. Sam-bot can comfortably fix ~7-8 P1+P2 bugs per
day within the remaining cap budget (each fix burns 1 R5 + 1 R4 retest
on PR merge = 2 runs).

P0 fixes get fast-tracked (interrupting other Routines if needed via
metered overage). P3 fixes wait for human review.

## What you do, in order

1. Implement Block 1 (homelab smoke) first. Get the heartbeat firing
   reliably. This alone multiplies bug-finding 4x.
2. Disable old Routine 1 (qa-smoke-90min) — homelab covers it now.
3. Implement Routines A, B, C, E as new entries in claude.ai/code/routines.
4. Keep Routine 2 (signup) unchanged.
5. Adjust Sam-bot scope budget upward (see Block 3) so it can keep
   pace with bug filing rate.
