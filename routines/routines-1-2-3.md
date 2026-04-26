# Claude Code Routines — Cloud-Sandbox Versions

These are the rewritten prompts for Routines 1, 2, and 3 in the same
path-discovery + sequential-roles pattern that fixed Routine 4. Paste each
prompt into the matching routine in `claude.ai/code/routines`.

## One-time setup, applies to ALL three routines

Each routine needs:

1. **Three repos attached** (same as Routine 4):
   - `RSA-Data-Solutions/always-on-engineering-fleet`
   - `RSA-Data-Solutions/iNova` (or whichever case is canonical)
   - `RSA-Data-Solutions/IBMiMCP`

2. **GitHub connector** with issues:write + PR access on those three repos.

3. **Environment variables** set on the routine (in the routine's settings
   panel, NOT in the prompt — secrets go in the env panel):
   - `QA_BASE_URL` = `https://inovaide.com`
   - `QA_BYPASS_SECRET` = (the same secret you set in iNova/.env)
   - `QA_TENANT_SMOKE_PASSWORD` = (qa-smoke@inovaide-qa.com password)
   - `QA_TENANT_EXPLORE_PASSWORD` = (qa-explore@inovaide-qa.com password)

4. **Cron trigger** (specific time per routine, see each section below).

---

## Routine 1 — Hourly Smoke (`qa-smoke-hourly`)

### Schedule

```
Cron:     5 12-4 * * *
Timezone: UTC
```

This translates to **:05 past every hour from 07:00 to 23:00 Central Time**
(UTC-5/-6 depending on DST), which gives:

- 17 runs per day
- Skips the 03:00–04:00 UTC pub400 maintenance window
- Within the 25 runs/day cap on Team plan (68% utilisation, leaves headroom
  for Routine 4 webhook fires)

If you're in a different timezone, adjust the hour range. The key is to
avoid 03:00–04:00 UTC.

### Prompt

```
You are the orchestrator (Ram) for an hourly P0 smoke run. No webhook
payload — this is a scheduled run against the live inovaide.com URL.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify paths to:
    - always-on-engineering-fleet  (your operating manual)
    - iNova                        (qa/ test suite)
    - IBMiMCP                      (tool inventory reference)

STEP 1 — Read your manual.
Read these files (use absolute paths):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You will play Ram, Lynn, and Sam roles sequentially in this single session.

STEP 2 — Maintenance window check.
If current UTC hour is 03 or 04, exit cleanly with note "skipped — pub400
maintenance window." No tickets, no heartbeat (the watchdog will accept a
single missed beat).

STEP 3 — Act as Lynn (QA).
Per agents/lynn.md, run the P0 suite ONLY against the live site:
    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

For each failure in /tmp/p0-report.json with failure_type "code_bug":
    - Apply Lynn's Step 5 ticket-filing rules (lynn.md)
    - Compute dedup_hash = sha256(target_repo + test_name + first_line(error) + tool_name)[:12]
    - Search existing open issues in target repo for "Dedup hash: {hash}"
    - If found: add a comment "Reoccurred at {now} on hourly smoke."
    - If not: create issue per lynn.md schema, labels: qa-bot, severity/Px

Special case — degradation rule:
    If ≥6 of 12 P0 tools fail in this single run, OR the same single P0
    tool failed in this AND the previous hourly run, file ONE
    severity/P0 issue titled "P0 SUITE DEGRADATION" in the iNova repo
    instead of multiple individual tickets. List the failing tools.

STEP 4 — Act as Sam (SE).
DO NOT push fixes from this routine. Hourly smoke is read-only on the
codebase. Sam's role here is limited to triaging classifications: if
Lynn flagged something as code_bug but the failure looks like
env_problem or flaky on second look, downgrade in qa-report and skip
the ticket.

STEP 5 — Heartbeat.
Append the current UTC ISO timestamp to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
Commit with message "heartbeat: qa-smoke-hourly {timestamp}" and push to
the fleet repo's main branch.

Hard limits:
- Total run time cap: 20 minutes. If exceeded, file ONE severity/P1 issue
  "Routine 1 timed out at {step}" in iNova repo and stop.
- Never commit secrets, passwords, or QA bypass tokens.
- Do NOT touch baseline_metrics.json — only Routine 4 updates it.
```

---

## Routine 2 — Daily Signup (`qa-signup-daily`)

### Schedule

```
Cron:     0 8 * * *
Timezone: UTC
```

This is **02:00 Central Time daily** (low traffic, good time for fresh
account creation that won't compete with real users on the live site).

- 1 run per day
- 4% of Team plan cap

### Prompt

```
You are the orchestrator for a daily fresh-signup regression. This runs
against the LIVE inovaide.com — every run creates a brand-new user.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify paths to:
    - always-on-engineering-fleet
    - iNova

STEP 1 — Read your manual.
Read:
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/lynn.md
    {fleet}/contexts/inova.md
You play Ram and Lynn in this session — no Aaron (we are not deploying),
no Sam (do not push fixes from a daily run).

STEP 2 — Act as Lynn (QA).
Per lynn.md, run the signup journey:
    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_BYPASS_SECRET=$QA_BYPASS_SECRET \
      python -m pytest ui_journey/test_signup.py -v \
      --json-report --json-report-file=/tmp/signup-report.json

The test:
    - generates a fresh email qa+{unix_timestamp}@inovaide-qa.com
    - sends signup with X-QA-Bypass HMAC header (skips email verify)
    - logs in, opens VS Code, waits for OpenCode CLI ready
    - invokes listTables as the first canonical tool call
    - asserts each step completes within thresholds in
      qa/baseline_metrics.json (signup_journey key) or DEFAULT_THRESHOLDS

STEP 3 — Triage and file.
For each failure in /tmp/signup-report.json:
    - Route ALL failures to RSA-Data-Solutions/iNova (signup is
      platform_failure by definition — even a tool call failure here
      means the journey didn't complete, which is platform-side)
    - Severity:
        - Step fails outright (signup, login, IDE boot, OpenCode init,
          first tool call) → severity/P0
        - Step exceeds threshold but completes → severity/P1
        - Email delivery >180s (if bypass disabled and real email used)
          → severity/P1
    - Apply dedup hash logic (same as Routine 1).
    - Add labels: qa-bot, platform-bug, auto-filed, severity/Px.

STEP 4 — Do NOT delete the created account.
Leave it in the database. A separate weekly GC routine prunes old
signup_bot accounts. Do NOT reuse the email — every run uses a fresh one.

STEP 5 — Heartbeat.
Append UTC timestamp to:
    {fleet}/fleet-workspace/heartbeats/qa-signup-daily.txt
Commit and push.

Hard limits:
- Run time cap: 10 minutes.
- Never log the QA_BYPASS_SECRET, the bypass token, or the test password.
```

---

## Routine 3 — Daily Exploratory + Rotation (`qa-explore-daily`)

### Schedule

```
Cron:     0 11 * * *
Timezone: UTC
```

This is **05:00 Central Time daily** — after pub400 maintenance, before
business hours. Gives Dhira time to research before any human is around.

- 1 run per day
- 4% of Team plan cap

### Prompt

```
You are the orchestrator for daily deep QA. Two phases — research then
rotation.

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify paths to:
    - always-on-engineering-fleet
    - iNova
    - IBMiMCP

STEP 1 — Read your manual.
Read:
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/dhira.md
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
    {fleet}/contexts/ibmimcp.md
You play Ram, Dhira, Lynn, and Sam sequentially.

STEP 2 — Act as Dhira (research). Time budget: 30 minutes.
Per dhira.md, search the public web for IBM i community complaints from
the LAST 24 HOURS that could affect inovaide.com or IBMiMCP:
    - reddit.com/r/IBMi (new posts)
    - code400.com forums (new threads)
    - GitHub issues filed in upstream MCP server projects
    - X / Mastodon mentions of "IBM i MCP" or "inovaide"
    - Issue trackers of both our repos for new community-filed issues

For each distinct pain pattern found:
    - Write a proposal to {fleet}/fleet-workspace/proposals/YYYY-MM-DD-{slug}.md
    - One proposal per pattern, max 5 proposals per run
    - Format per dhira.md template
    - These are FLEET PROPOSALS for CTO review, NOT customer tickets.
      Do not file these to GitHub Issues.

If Dhira finds nothing actionable in 30 min, write a single proposal
"YYYY-MM-DD-no-signal.md" with a one-line note. This is fine — quiet days
exist. Don't manufacture concerns.

STEP 3 — Act as Lynn (QA rotation).
Determine today's batch from contexts/inova.md rotation_batches:
    today=$(date -u +%A)
Look up rotation_batches[$today]. If empty, skip Lynn entirely and go to
Step 5 — the rotation lists are populated incrementally by Sam and may
not all be defined yet.

If batch is defined, run:
    cd {iNova}/qa
    source .venv/bin/activate   # venv created by previous routines
    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_TENANT_EXPLORE_PASSWORD=$QA_TENANT_EXPLORE_PASSWORD \
      python -m pytest ui_journey/test_rotation.py -v \
      --rotation-day=$today \
      --json-report --json-report-file=/tmp/rotation-report.json

Apply Lynn's Step 5 ticket-filing rules. Be RUTHLESS on classification:
    - If repro isn't crisp in 3 lines, downgrade to a Dhira proposal
      instead of filing a ticket. Exploratory noise erodes trust.
    - severity/P2 default for non-P0 tool failures.
    - Add `routine-3-explore` label so triage can distinguish exploratory
      finds from smoke finds.

STEP 4 — Act as Sam (SE).
For tickets filed in Step 3, propose fixes only — do NOT push to main.
Write fix branches to {fleet}/fleet-workspace/hotfix/ as per sam.md.
A human reviews these the next morning and decides whether to merge.

STEP 5 — Discover newly added IBMiMCP tools.
Once per week (only on Sunday based on date -u +%u == 7), update the
rotation batch list in {iNova}/qa/ui_journey/test_rotation.py:
    - Read {IBMiMCP}/src/tools/ directory recursively
    - Map each tool file to its directory bucket
    - Subtract P0 tools (defined in contexts/inova.md → P0 Tool Suite)
    - Distribute remaining tools across the 7 weekday batches
    - Open a PR titled "chore(qa): refresh rotation batches" against iNova

STEP 6 — Heartbeat.
Append UTC timestamp to:
    {fleet}/fleet-workspace/heartbeats/qa-explore-daily.txt
Commit and push.

Hard limits:
- Run time cap: 60 minutes (Dhira can be slow; that's expected).
- Maximum 10 tickets filed per run. If Lynn would file more, file ONE
  severity/P1 "Tool batch broadly broken — see qa-report" issue instead.
- Never commit research notes that include user PII or competitor IP.
```

---

## Recommended rollout order (do not enable all at once)

Day 0: Routine 2 only (daily signup)
   → wait one full day, watch one cycle complete

Day 2: Add Routine 1 (hourly smoke)
   → wait 24 hours, confirm 17 sessions in history

Day 3: Add Routine 3 (daily exploratory)
   → wait one full day

Day 4 onward: All four routines live, watchdog watching.

---

## Cap accounting (Team plan, 25 runs/day)

```
R1 hourly smoke      17 runs/day  (68%)
R2 signup daily       1 run/day   (4%)
R3 explore daily      1 run/day   (4%)
R4 post-deploy        webhook (variable, metered overage)
                     ─────────────
total scheduled:     19 runs/day  (76%)
```

Pro plan (5/day) and Max plan (15/day) both cannot accommodate this
schedule. Team is the floor. Enterprise gives more headroom on R4
overage on heavy-deploy days.
