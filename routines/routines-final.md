# Claude Code Routines — 15-run cap + fix-and-retest loop

Updated routine plan. Two changes from the previous version:

1. Scheduled runs compressed to fit 15/day cap (was 19).
2. Added Routine 5 (Sam auto-fix on issue) and extended Routine 4 to
   handle retest + close-or-reopen.

The result is a self-closing QA loop: Lynn finds a bug, Sam proposes
a fix, human merges, Routine 4 verifies and closes the issue.

---

## Cap accounting (Max plan, 15 runs/day)

```
R1 smoke (every 90min) 11 runs/day  (73%)
R2 signup daily         1 run/day   (7%)
R3 explore daily        1 run/day   (7%)
                       ────────────
total scheduled:       13 runs/day  (87%)

reserve for:
R4 post-deploy         webhook (event-driven, but counts against cap)
R5 fix-on-issue        webhook (event-driven, counts against cap)

Plan ~2 reserve runs/day for fix-and-retest cycles. On heavy fix days
this will exceed cap — enable metered overage in billing settings.
```

If you're on Max (15/day) and bug count is high for a while, expect
overage charges. Once the codebase stabilises, R5 fires get rare and
you settle back under cap.

---

## Routine 1 — Smoke (every 90 min) — `qa-smoke-90min`

### Schedule

```
Cron:     5 12,13,15,16,18,19,21,22,0,1,3 * * *
Timezone: UTC
```

11 runs/day, every 90 min from 07:05 to 22:35 Central Time, skipping
03:00–06:00 UTC (pub400 maintenance).

If your Routines UI rejects the long comma list, the equivalent in
"every N minutes within window" form may not be expressible — split
into two cron lines if the UI supports multiple, otherwise paste the
comma form.

### Prompt

(Same as previous "Routine 1 — Hourly Smoke" prompt with one change:
remove the maintenance-window check in STEP 2 since the cron already
excludes those hours. Otherwise identical.)

```
You are the orchestrator (Ram) for a 90-minute P0 smoke run.

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
    {fleet}/agents/lynn.md
    {fleet}/agents/sam.md
    {fleet}/contexts/inova.md
You play Ram, Lynn, and Sam sequentially.

STEP 2 — Act as Lynn (QA).
    cd {iNova}/qa
    python3 -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium
    QA_HEADLESS=true \
    QA_BASE_URL=$QA_BASE_URL \
    QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
      python -m pytest ui_journey/test_p0_suite.py -v \
      --json-report --json-report-file=/tmp/p0-report.json

For each code_bug failure:
    - Apply Lynn's Step 5 ticket-filing rules (lynn.md)
    - Compute dedup_hash, search open issues, comment if dup or create
      new with labels: qa-bot, severity/Px, needs-fix
    - The `needs-fix` label is what triggers Routine 5

Degradation rule:
    If ≥6 of 12 P0 tools fail in this run, OR same single tool failed
    in this AND previous run, file ONE severity/P0 issue
    "P0 SUITE DEGRADATION" instead of multiple — listing failing tools.

STEP 3 — Act as Sam (triage only, no fixes).
Sam is read-only this routine. If Lynn flagged something as code_bug
but it looks more like env_problem on second look, downgrade in
qa-report and skip ticket creation. Do NOT push fixes from smoke.

STEP 4 — Heartbeat.
Append UTC timestamp to:
    {fleet}/fleet-workspace/heartbeats/qa-smoke-90min.txt
Commit and push.

Hard limits:
- Run cap: 20 minutes
- Never log secrets
- Do NOT touch baseline_metrics.json
```

---

## Routine 2 — Daily Signup — `qa-signup-daily`

### Schedule

```
Cron:     0 8 * * *
Timezone: UTC
```

02:00 Central Time daily.

### Prompt

(Same as previous Routine 2 — no changes needed. Keep the existing prompt.)

---

## Routine 3 — Daily Exploratory — `qa-explore-daily`

### Schedule

```
Cron:     0 11 * * *
Timezone: UTC
```

05:00 Central Time daily.

### Prompt

(Same as previous Routine 3 — no changes needed. Keep the existing prompt.)

---

## Routine 4 — Post-deploy regression — `qa-release-regression`

### Trigger

Webhook (existing). Fired by `release-qa.yml` GitHub Action on push
to main in either iNova or IBMiMCP repos.

### Updated prompt

The new logic at the end is what closes the loop. Lynn's normal
regression suite runs as before, then Step 5 inspects the commit's
linked issues to verify fixes:

```
You are the orchestrator for post-deploy regression.

STEP 0–3: same as before — discover paths, read manual, Aaron deploys,
Lynn runs the full suite + diffs against baseline_metrics.json.

(Existing severity rules apply: P0 regression >20% → severity/P0,
 functionally broken P0 → severity/P0, etc.)

STEP 4 — Update baseline.
If suite passed clean (zero new tickets, zero regressions): open a PR
against the iNova repo updating qa/baseline_metrics.json with new P95s.
On any failure: do NOT touch baseline_metrics.json.

STEP 5 — Close the loop on Sam-fixed issues.   ← NEW
The merged commit may have the form "Fixes #N" closing one or more
qa-bot issues. For each issue closed by this commit:

    a) Find the issue's original failing test from its body
       (Lynn's filing template includes the test_name field).

    b) Look up that test's result in /tmp/regression-report.json:

       Test passed in this regression run:
           - Comment on the issue: "Verified fixed by {sha} in {session_url}."
           - Issue stays closed.

       Test still failing:
           - Reopen the issue (GitHub API: PATCH /issues/N state=open)
           - Add label: false-fix
           - Comment: "Sam's fix in {sha} merged but the test that
             originally failed is STILL failing. See {session_url}.
             Original failure preserved below."
           - Bump severity by one level (P1 → P0, P2 → P1).
           - This means human review next time around — do NOT add
             needs-fix back, or Routine 5 will loop infinitely.

    c) New tests failing that weren't failing before this commit:
           - File a fresh issue with label `regression-after-fix`
           - Reference the merged commit and prior issues in the body

STEP 6 — Heartbeat.
Append UTC timestamp + commit SHA to:
    {fleet}/fleet-workspace/heartbeats/qa-release-{sha[:8]}.txt

Hard limits:
- Run cap: 45 minutes
- Never auto-merge anything; PRs require human approval
```

---

## Routine 5 — Sam Auto-Fix — `qa-fix-on-issue-open` (NEW)

This is the routine that closes the "always-on engineering" loop. When
Lynn files a P0 or P1 issue, Sam picks it up and proposes a fix in a PR.

### Trigger

GitHub webhook → set up a Repository Dispatch event from a tiny GitHub
Action that watches issue creation:

```yaml
# Add to BOTH iNova and IBMiMCP repos as
# .github/workflows/qa-bot-fix-trigger.yml

name: Trigger Sam auto-fix
on:
  issues:
    types: [labeled]

jobs:
  trigger-fix:
    if: |
      contains(github.event.issue.labels.*.name, 'qa-bot') &&
      contains(github.event.issue.labels.*.name, 'needs-fix') &&
      (contains(github.event.issue.labels.*.name, 'severity/P0') ||
       contains(github.event.issue.labels.*.name, 'severity/P1'))
    runs-on: ubuntu-latest
    steps:
      - name: Fire Sam fix routine
        env:
          ROUTINE_FIRE_URL: ${{ secrets.SAM_FIX_ROUTINE_URL }}
          ROUTINE_FIRE_TOKEN: ${{ secrets.SAM_FIX_ROUTINE_TOKEN }}
        run: |
          set -euo pipefail
          [[ -z "$ROUTINE_FIRE_URL" ]] && exit 0

          text=$(jq -n \
            --arg repo "${{ github.repository }}" \
            --arg num "${{ github.event.issue.number }}" \
            --arg title "${{ github.event.issue.title }}" \
            '"qa_issue_repo=" + $repo + "\n" +
             "qa_issue_number=" + $num + "\n" +
             "qa_issue_title=" + $title')

          curl -sS -X POST "$ROUTINE_FIRE_URL" \
            -H "Authorization: Bearer $ROUTINE_FIRE_TOKEN" \
            -H "anthropic-version: 2023-06-01" \
            -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg t "$text" '{text: $t}')"
```

Get `SAM_FIX_ROUTINE_URL` and `SAM_FIX_ROUTINE_TOKEN` from this
routine's API trigger panel and add them as GitHub secrets in BOTH
repos.

### Prompt

```
You are Sam (Software Engineer agent). A QA-bot issue was just filed
with severity/P0 or P1 + needs-fix labels. Your job: read the issue,
write a fix, open a PR, and remove the needs-fix label.

The text field contains:
    qa_issue_repo=RSA-Data-Solutions/<repo>
    qa_issue_number=<N>
    qa_issue_title=<title>

STEP 0 — Discover repo paths.
Run: ls -la ~ /workspace 2>/dev/null
Identify paths to:
    - always-on-engineering-fleet
    - iNova (and/or) IBMiMCP

STEP 1 — Read your manual.
Read:
    {fleet}/SKILL.md
    {fleet}/agents/sam.md
    {fleet}/agents/ram.md     (for push authority rules)
    {fleet}/contexts/inova.md
    OR {fleet}/contexts/ibmimcp.md depending on qa_issue_repo

STEP 2 — Read the issue.
Use GitHub API:
    GET /repos/{qa_issue_repo}/issues/{qa_issue_number}

Extract from the body:
    - Steps to reproduce
    - Expected vs Actual
    - test_name (Lynn's template includes this)
    - tool_name if applicable
    - Build / commit_sha

STEP 3 — Reproduce locally.
    cd {target_repo}
    git checkout -b qa-bot/fix-{qa_issue_number}-{first8(dedup_hash)}
    # Read the failing test:
    grep -rn "{test_name}" qa/ tests/   # find the assertion that failed
    # Reproduce:
    [run the failing test exactly as Lynn ran it]

If you cannot reproduce: comment on the issue
    "Sam-bot tried to reproduce but the test passed locally on
     branch {branch} commit {sha}. This may be flaky — adding
     `needs-human-review` label and removing `needs-fix`."
Then add label `needs-human-review`, remove `needs-fix`, STOP.

STEP 4 — Diagnose and fix.
Per sam.md:
    - Read related code (use grep/ast tools, don't guess)
    - Form a hypothesis
    - Make the smallest change that fixes the test
    - Re-run the failing test — must pass
    - Re-run adjacent tests — must still pass
    - Run linters per the repo's CI config

If the fix touches >5 files or >100 lines, STOP and add label
`needs-human-review` with comment "Fix scope exceeds Sam-bot
auto-fix budget. Diff attached as artifact for human review."
Push the branch but do not open the PR.

STEP 5 — Open the PR.
    git add -A
    git commit -m "fix({tool_or_area}): {short description}

    Fixes #{qa_issue_number}

    QA-bot found regression in {test_name}.
    Root cause: {one sentence}.
    Fix: {one sentence}.

    Verified locally: failing test now passes, adjacent tests unchanged.

    Co-authored-by: Sam (always-on-engineering-fleet) <bot@inovaide.com>"

    git push origin {branch}

Open PR via GitHub API:
    POST /repos/{repo}/pulls
    title: same as commit
    body: include "Fixes #{qa_issue_number}" + session_url for traceability

STEP 6 — Update the issue.
Comment on issue:
    "Sam-bot proposed fix in PR #{pr_number}. Awaiting human review.
     Once merged, Routine 4 will retest and close this issue (or
     reopen with `false-fix` if the test still fails)."

Remove label: needs-fix
Add labels:    awaiting-human-review, has-proposed-fix

STEP 7 — Heartbeat.
Append to {fleet}/fleet-workspace/heartbeats/qa-fix-on-issue.txt:
    {timestamp} issue=#{qa_issue_number} pr=#{pr_number} repo={repo}

Hard limits:
- Run cap: 30 minutes per issue
- Max 5 files modified
- Max 100 lines changed
- NEVER push directly to main — only feature branches
- NEVER auto-merge a PR
- NEVER touch CI/CD pipelines, secrets, or auth code without
  `auth-touch-allowed` label on the issue (which a human applies)
- If hard limits hit, add `needs-human-review` and stop gracefully
```

---

## The full lifecycle of a QA-found bug, end-to-end

```
T+0    Routine 1 fires (smoke). Lynn finds runSQL returning timestamps
       in wrong format.
T+1m   Lynn files issue #847 in IBMiMCP repo:
           labels: qa-bot, tool-bug, severity/P1, needs-fix
T+1m   GitHub Action `qa-bot-fix-trigger.yml` fires on the labeled event.
       Webhook hits Routine 5.
T+2m   Routine 5 (Sam-bot) starts. Reads issue #847.
T+5m   Sam reproduces locally on branch `qa-bot/fix-847-a1b2c3d4`.
T+12m  Sam writes fix in src/tools/sql/runSQL.ts.
T+13m  Sam opens PR #312 "fix(runSQL): coerce timestamps to ISO 8601",
       comments on issue, swaps `needs-fix` → `awaiting-human-review`.

[Human reviews PR #312 morning of next business day, merges to main]

T+next-day  Push to main fires Routine 4 (qa-release-regression).
T+next-day+5m   Routine 4 deploys, runs full suite.
T+next-day+15m  Suite green. test_runSQL_timestamp_format passes.
                Routine 4 sees PR closed issue #847 in commit message,
                comments "Verified fixed by abc123. Closing." Issue closed.

[The loop is closed. No human had to do anything except merge the PR.]
```

If at any point Sam can't reproduce, can't fix, or the fix's scope is
too big, Sam adds `needs-human-review` and bows out. The fleet falls
back to humans gracefully — it never silently abandons issues.

---

## What needs to be created/added

In claude.ai/code/routines:
   - Routine 1 (qa-smoke-90min) — schedule + prompt above
   - Routine 2 (qa-signup-daily) — schedule + previous prompt
   - Routine 3 (qa-explore-daily) — schedule + previous prompt
   - Routine 5 (qa-fix-on-issue-open) — webhook trigger + prompt above
   - Edit Routine 4 — append STEP 5 (close-or-reopen logic)

In iNova/.github/workflows/ AND IBMiMCP/.github/workflows/:
   - qa-bot-fix-trigger.yml — the YAML above
   - Add secrets: SAM_FIX_ROUTINE_URL, SAM_FIX_ROUTINE_TOKEN

Issue label setup (one-time, in both repos):
   gh label create qa-bot --color "0E8A16"
   gh label create tool-bug --color "D93F0B"
   gh label create platform-bug --color "B60205"
   gh label create needs-fix --color "FBCA04"
   gh label create awaiting-human-review --color "5319E7"
   gh label create has-proposed-fix --color "1D76DB"
   gh label create false-fix --color "B60205"
   gh label create regression-after-fix --color "B60205"
   gh label create needs-human-review --color "FBCA04"
   gh label create severity/P0 --color "B60205"
   gh label create severity/P1 --color "D93F0B"
   gh label create severity/P2 --color "FBCA04"
   gh label create severity/P3 --color "0E8A16"
   gh label create routine-3-explore --color "C5DEF5"
   gh label create release-blocker --color "B60205"
