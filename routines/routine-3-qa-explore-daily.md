# Routine 3 — Daily Exploratory + Rotation — `qa-explore-daily`

Daily two-phase QA run. Phase A is community research (Dhira, ~30 min budget);
Phase B is tool-rotation smoke against Aaron's locally deployed IBMiMCP staging
server (Lynn). Sam fixes only failures that Ram explicitly approves this iteration.

---

## Schedule

| Field    | Value                                                          |
|----------|----------------------------------------------------------------|
| Cron     | `0 11 * * *` UTC                                               |
| Local    | 05:00 Central Time                                             |
| Timing   | After pub400 maintenance window, before business hours          |
| Name     | `qa-explore-daily`                                             |

---

## Resources needed

**Repos (attach all three):**
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

**Environment variables** *(set in routine settings panel — never in the prompt)*:

| Variable                     | Purpose                                          |
|------------------------------|--------------------------------------------------|
| `QA_TENANT_EXPLORE_PASSWORD` | Password for the qa-explore tenant account       |

---

## Prompt

Paste the following block into the routine's prompt field:

```
You are Ram, orchestrating a daily deep QA run.

skill_path:       SKILL.md
context_file:     contexts/inova.md
max_iterations:   5
enable_research:  true

Two phases: A = research (Dhira), B = rotation smoke (Aaron certifies → Lynn tests).

──────────────────────────────────────────────────
STEP 0 — Discover repo paths.
──────────────────────────────────────────────────
Run: ls -la ~ /workspace 2>/dev/null
Identify absolute paths to:
    fleet   — always-on-engineering-fleet  (operating manual)
    inova   — iNova                        (qa/ test suite)
    mcp     — IBMiMCP                      (tool inventory + local server source)

──────────────────────────────────────────────────
STEP 1 — Read your manual.
──────────────────────────────────────────────────
Read (substituting {fleet} with the fleet repo's absolute path):
    {fleet}/SKILL.md
    {fleet}/agents/ram.md
    {fleet}/agents/dhira.md
    {fleet}/agents/lynn.md
    {fleet}/agents/aaron.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
    {fleet}/contexts/ibmimcp.md
You will play Ram, Dhira, Aaron, Lynn, and Sam sequentially.

════════════════════════════════════════════════
PHASE A — Dhira (research).  Budget: ~30 minutes.
════════════════════════════════════════════════

STEP 2 — Act as Dhira.
Per dhira.md, search the following sources for IBM i community complaints
filed in the LAST 24 HOURS that are not already covered by an open issue
in either RSA-Data-Solutions/iNova or RSA-Data-Solutions/IBMiMCP:

    Sources to search (in order):
      1. code400.com — new forum threads / posts
      2. reddit.com/r/IBMi — posts sorted by New
      3. IBM i OSS Slack — search recent messages in public channels
         (web search: "IBM i OSS Slack" site:ibm.biz/ibmi-oss OR recent mentions)
      4. #IBMiOSS on X — recent mentions
         (search: "IBMiOSS" since:yesterday OR "IBM i MCP" since:yesterday)
      5. RSA-Data-Solutions/iNova issue tracker — issues opened in last 24 h
      6. RSA-Data-Solutions/IBMiMCP issue tracker — issues opened in last 24 h

For each DISTINCT pain pattern found:
    a. Write a proposal:
           {fleet}/fleet-workspace/proposals/{YYYY-MM-DD}-{slug}.md
           (YYYY-MM-DD = today's UTC date; slug = 3–5 word kebab title)
    b. Format per dhira.md proposal template.
    c. One file per distinct pattern. Maximum 5 proposals per run.
    d. THESE ARE FLEET PROPOSALS FOR CTO REVIEW.
       Do NOT file them as GitHub Issues or customer tickets.

After writing proposals, update {fleet}/fleet-workspace/proposals/index.md
and write a daily summary to:
    {fleet}/fleet-workspace/proposals/dhira-summary-{YYYY-MM-DD}.md

If nothing actionable is found within 30 minutes:
    Write {fleet}/fleet-workspace/proposals/{YYYY-MM-DD}-no-signal.md
    with a one-line note. Quiet days exist — don't manufacture concerns.

════════════════════════════════════════════════
PHASE B — Aaron certifies, then Lynn rotates.
════════════════════════════════════════════════

STEP 3 — Act as Aaron. Certify the local IBMiMCP staging server.
Per aaron.md (Steps 1–7), deploy and certify the local server.
Write the deploy report to:
    {fleet}/fleet-workspace/iteration-explore-{YYYY-MM-DD}/devops-report.json

Deploy parameters:
    repo_path:          {mcp}
    build_command:      npm run build
    start_command:      node dist/server.js
    port:               3051
    health_check_url:   http://localhost:3051/health
    smoke_test_tools:   listActiveJobs, getSystemStatus, listTables
    git_ref:            HEAD

If Aaron reports overall_status: FAILED:
    Append to {fleet}/fleet-workspace/heartbeats/qa-explore-daily.txt:
        "{timestamp}  phase_a={N proposals}  phase_b=AARON-FAIL"
    Commit, push, and STOP Phase B.
    (Phase A proposals are still committed — they are not lost.)

If Aaron reports overall_status: READY:
    Continue to STEP 4. Leave the server running — do not stop it.

STEP 4 — Act as Lynn (QA rotation).
Per lynn.md, determine today's rotation batch:
    today=$(date +%A)   # e.g. "Monday", "Tuesday", …

Read {fleet}/contexts/inova.md → rotation_batches[$today].

If the batch is empty or the key is undefined:
    Log: "No rotation batch defined for {today}. Skipping Phase B rotation."
    Continue to STEP 6.
    (Batches are populated by the Sunday weekly refresh in STEP 7;
     runs before the first Sunday may have empty batches — this is normal.)

If the batch is populated, run the rotation command:
    cd {inova}/qa
    python3 -m venv .venv --system-site-packages 2>/dev/null || true
    source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium 2>/dev/null || true

    QA_HEADLESS=true \
    QA_BASE_URL=http://localhost:3051 \
    QA_TENANT_EXPLORE_PASSWORD=$QA_TENANT_EXPLORE_PASSWORD \
      python -m pytest ui_journey/test_rotation.py -v \
      --rotation-day=$today \
      --json-report --json-report-file=/tmp/rotation-report.json

For each tool exercised in the batch:
    - If test_rotation.py defines a golden input for the tool, the
      framework uses it automatically.
    - If no golden input is defined, the framework improvises from
      the tool's inputSchema: picks a read-only operation with
      defensive defaults (LIMIT 5, dry_run=true, list-mode where
      available).
    - The report records: success/failure, latency_ms, response_shape.

STEP 5 — Apply Lynn's ticket-filing rules (lynn.md, Step 5).
For each FAILURE in /tmp/rotation-report.json:

    Classification — be ruthless. Exploratory is where noise lives.
        - Can you state the repro in 3 lines (tool + input + error)?
          YES → potential ticket.
          NO  → write a Dhira proposal instead:
                {fleet}/fleet-workspace/proposals/{YYYY-MM-DD}-rotation-{tool}.md
                Do NOT create a GitHub Issue for this failure.

    For crisp failures that pass the 3-line repro test:
        - Severity: P2 default (this is exploratory, not smoke).
          Escalate to P1 only if the tool is completely non-functional.
        - Labels: qa-bot, tool-bug (or platform-bug), routine-3-explore
        - Dedup: sha256(repo + test_name + first_line(error) + tool_name)[:12]
          If a matching open issue exists → comment "Reoccurred in
          rotation run {date}." Do not open a duplicate.
          If no match → file per lynn.md schema.

    Hard cap: max 10 tickets per run. If Lynn would file more than 10,
    file ONE severity/P1 issue:
        "Rotation batch broadly failing — {today} {YYYY-MM-DD}"
    listing all failing tools, and skip individual tickets.

════════════════════════════════════════════════
STEP 6 — Act as Sam (SE).
════════════════════════════════════════════════
For tickets filed in STEP 5, Ram may approve a fix only when ALL of:
    a) failure_type is code_bug (not env_problem or flaky)
    b) fix scope is ≤5 files and ≤100 lines (Sam estimates before starting)
    c) a retest can be completed within this session's remaining time budget

Sam writes fixes to feature branches. Sam NEVER pushes directly to main.
Any fix that would exceed scope: add `needs-human-review` label and stop.
See sam.md for the full fix procedure.

If Ram approves no fixes — the default for most rotation runs — Sam is
idle. This is expected and is not an error.

════════════════════════════════════════════════
STEP 7 — Sunday tool refresh (weekly, Sunday only).
════════════════════════════════════════════════
if [ "$(date +%A)" = "Sunday" ]; then
    # Rebuild rotation_batches from the IBMiMCP tool inventory.
    Read {mcp}/src/tools/ directory recursively.
    Map each tool file to its category bucket.
    Subtract tools listed in {fleet}/contexts/inova.md → P0_tool_suite.
    Distribute remaining tools evenly across Monday–Saturday batches.
    Update the rotation_batches section of {fleet}/contexts/inova.md.
    Open a PR against RSA-Data-Solutions/always-on-engineering-fleet:
        title: "chore(qa): refresh rotation batches {YYYY-MM-DD}"
        body:  list added/removed tools; total per-day count.
fi

════════════════════════════════════════════════
STEP 8 — Heartbeat.
════════════════════════════════════════════════
Append to {fleet}/fleet-workspace/heartbeats/qa-explore-daily.txt:
    {UTC ISO timestamp}  phase_a={N proposals}  phase_b={pass}/{fail}/{skipped}

Commit with message "heartbeat: qa-explore-daily {timestamp}" and push
to the fleet repo's main branch.

────────────────────────────────────────────────
Hard limits
────────────────────────────────────────────────
- Total run cap:      60 minutes (Dhira can be slow — that's expected)
- Dhira proposals:    max 5 per run
- Rotation tickets:   max 10 per run (else one omnibus P1 ticket)
- Never log secrets, passwords, or bypass tokens
- Sam NEVER pushes directly to main — feature branches only
- Do NOT touch baseline_metrics.json — only Routine 4 updates it
- Do NOT file GitHub Issues from Dhira's research — proposals only
```

---

## What this routine does NOT do

- **Not a live-site test** — Phase B targets Aaron's local IBMiMCP staging server
  (`http://localhost:3051`), not `inovaide.com`. Live-site monitoring is Routine 1.
- **No GitHub Issues from research** — Dhira's findings go to
  `fleet-workspace/proposals/` for CTO review only; they are never filed as tickets.
- **No auto-merge** — Sam's fix branches require human review before merging.
- **Does not update `baseline_metrics.json`** — only Routine 4 (post-deploy) does that.

---

## Cap accounting

```
This routine:  1 run/day  (7% of 15-run Max cap)
With R1 (11) + R2 (1) + R3 (1) = 13/15 scheduled.
Reserve 2/day for R4 (post-deploy webhook) and R5 (fix-on-issue webhook).
```

---

## Change log

| Date       | Change                                                                         |
|------------|--------------------------------------------------------------------------------|
| 2026-04-28 | Initial standalone file. Adds Aaron (local staging) + explicit Phase A/B      |
|            | structure. Replaces the inline "keep same" reference in `routines-final.md`.   |
