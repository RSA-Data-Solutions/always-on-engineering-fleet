# Routine 1 — Hourly Smoke (`qa-smoke-hourly`)

**Version:** deploy-first (Aaron + Lynn + Sam)
**Replaces:** the read-only live-site version in `routines-1-2-3.md`

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (configure in the routine's settings panel)
```

Fires at **:05 past every hour from 07:00 to 23:00** (local time).
The cron itself does not fire during 03:00–04:00 UTC where pub400 runs
nightly maintenance — adjust the hour window if your local timezone
shifts the UTC equivalent into that window.

---

## Setup (one-time, same as other routines)

1. **Three repos attached:**
   - `RSA-Data-Solutions/always-on-engineering-fleet`
   - `RSA-Data-Solutions/iNova`
   - `RSA-Data-Solutions/IBMiMCP`

2. **GitHub connector** with `issues:write` + PR access on all three repos.

3. **Environment variables** (routine settings panel — not in the prompt):
   - `QA_TENANT_SMOKE_PASSWORD` — qa-smoke@inovaide-qa.com password
   - Any other secrets referenced in `contexts/inova.md`

4. **Cron trigger:** `5 7-23 * * *` in the timezone configured above.

---

## Prompt

Paste verbatim into the routine's prompt field:

```
Launch the Ram agent (agents/ram.md) with:

  skill_path:         SKILL.md
  context_file:       contexts/inova.md
  max_iterations:     3
  enable_research:    false
  human_instructions: |
    Hourly P0 smoke. Inner loop:

    1. Aaron: deploy inovaide.com stack from latest main. Verify IBMiMCP
       connection is healthy and registered_tool_count ≥ 130. If Aaron
       reports FAILED, file ONE platform_failure ticket titled "Aaron
       deploy failed" and stop — do not run QA against a broken build.

    2. Lynn: run ui_journey_p0_suite_command against the Aaron-certified
       server. Exercises all 12 P0 tools via the qa-smoke tenant against
       pub400.com. Apply Step 5 ticket-filing rules in lynn.md.

    3. Sam: fix only code_bug failures. Ignore env_problem and flaky this
       routine — they belong to Routine 3.

    4. If ≥6 of 12 P0 tools fail in a single run, OR if the same single
       P0 tool fails in TWO consecutive hourly runs: open ONE severity/P0
       issue "P0 SUITE DEGRADATION" in the inova repo instead of 12
       individual tickets. Include the failing tool list.

    5. Write a heartbeat: fleet-workspace/heartbeats/qa-smoke-hourly.txt
       containing the current UTC timestamp. The external watchdog reads
       this; missing heartbeat = silent routine failure.

    Green builds: Ram pushes via normal authority. Do not push if any P0
    ticket is open.
```

---

## How Ram executes this

Ram reads the above as `human_instructions` and runs the following inner
loop (up to `max_iterations: 3`):

```
STEP 1 — Aaron (deploy)
  • Pull latest main in the iNova and IBMiMCP repos
  • Build and start the inovaide.com stack per contexts/inova.md
  • Run health check: GET /health → 200
  • Verify IBMiMCP connection healthy and registered_tool_count ≥ 130
  • If FAILED: file ONE issue in iNova repo
      title:  "Aaron deploy failed"
      labels: platform_failure, severity/P0, qa-bot
    Then STOP — do not proceed to QA.
  • If READY: continue

STEP 2 — Lynn (QA)
  • Run ui_journey_p0_suite_command against the Aaron-certified server
  • server_already_running: true (Aaron already started it)
  • Suite exercises all 12 P0 tools via qa-smoke tenant → pub400.com
  • Apply lynn.md Step 5 ticket-filing rules for each failure
  • Compute dedup_hash per lynn.md; comment on existing open issues
    rather than filing duplicates

STEP 3 — Degradation check (after Lynn, before Sam)
  • Count distinct P0 tools that failed this run
    If ≥ 6 of 12: collapse to ONE severity/P0 issue
      title:  "P0 SUITE DEGRADATION"
      labels: severity/P0, qa-bot
      body:   list of failing tools + run timestamp
      → do NOT file individual per-tool tickets this run
  • Check if any single tool also failed in the immediately previous
    hourly run (search open issues for that tool filed ≤ 90 min ago):
    If same tool failed twice consecutively: escalate / open ONE
      severity/P0 "P0 SUITE DEGRADATION" issue if not already opened
      above; add the tool name to its body

STEP 4 — Sam (fix)
  • Fix only failures classified as code_bug by Lynn
  • Ignore env_problem and flaky — do not file or touch those
  • Follow sam.md constraints (≤5 files, ≤100 lines per fix)
  • Re-run the failing test after each fix to confirm resolution
  • Do NOT push directly to main — fixes accumulate for Ram to push

STEP 5 — Heartbeat
  • Append current UTC ISO timestamp to:
      fleet-workspace/heartbeats/qa-smoke-hourly.txt
  • Commit: "heartbeat: qa-smoke-hourly {timestamp}"
  • Push to fleet repo (always, even if QA found failures)

STEP 6 — Push (conditional)
  • Query open issues in inova repo with label severity/P0
  • If ANY P0 issue is open: do NOT push code changes
  • If zero P0 issues open AND fixes exist: push per ram.md push rules
    commit: "fix: P0 smoke fixes [fleet hourly N]" with test evidence
```

---

## Heartbeat contract

The external watchdog polls
`fleet-workspace/heartbeats/qa-smoke-hourly.txt` after each expected
fire. A missing or stale timestamp (> 90 minutes old without a new
entry) is treated as a silent routine failure and pages the on-call.

Format — one line per run, appended:
```
2026-04-27T08:05:12Z  ok   aaron=READY  p0_pass=12/12
2026-04-27T09:05:44Z  ok   aaron=READY  p0_pass=11/12  filed=1
2026-04-27T10:05:03Z  DEGRADED  aaron=READY  p0_pass=4/12  filed=P0-SUITE
2026-04-27T11:05:31Z  FAILED  aaron=FAILED  filed=aaron-deploy-failed
```

Ram writes this line at STEP 5 regardless of pass/fail status.

---

## Cap accounting

```
Runs per day (07:00–23:00 = 17 hours):  17 runs/day
Team plan (25/day):                     68% utilisation
Max plan  (15/day):                     EXCEEDS CAP — use Team plan

Leaves headroom for Routine 4 (post-deploy webhook) and
Routine 5 (Sam fix-on-issue) overage.
```

---

## Relationship to other routines

| Routine | What it tests | Sam fixes? | Aaron deploys? |
|---------|--------------|------------|----------------|
| 1 (this) | P0 suite, hourly | code_bug only | Yes — from latest main |
| 2 | Signup journey, daily | No | No — tests live site |
| 3 | Exploratory rotation, daily | Proposes only | No — tests live site |
| 4 | Full regression, post-deploy webhook | Via PR | Yes — from pushed commit |
| 5 | Single issue fix, webhook | Yes | No |

env_problem and flaky failures from this routine are left for
Routine 3 (daily exploratory) to investigate and triage.
