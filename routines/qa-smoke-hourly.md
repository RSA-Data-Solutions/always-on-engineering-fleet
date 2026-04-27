# Routine 1 — Hourly Smoke (P0 suite + deploy)

Paste-ready spec for `claude.ai/code/routines`.

## Routine name

`qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

17 runs per day at :05 past every hour from 07:00 to 23:00 (local time).
This schedule naturally avoids the pub400.com maintenance window (03:00–04:00 UTC)
and stays within the Team plan 25-run/day cap.

## Trigger

Cron (scheduled). Not a webhook.

## Repos to attach

- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

## GitHub connector

Requires issues:write + PR access on all three repos.

## Environment variables (set in routine settings panel, not the prompt)

- `QA_BASE_URL` — base URL of the Aaron-deployed local staging instance
- `QA_BYPASS_SECRET` — HMAC secret matching iNova staging `.env`
- `QA_TENANT_SMOKE_PASSWORD` — password for `qa-smoke@inovaide-qa.com`

Do not hardcode any of these in the prompt. Aaron reads `QA_BASE_URL` when
verifying the deployment endpoint; Lynn reads it when targeting the test suite.

## Prompt (paste this into the routine)

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
       reports FAILED, file ONE platform_failure ticket titled “Aaron
       deploy failed” and stop — do not run QA against a broken build.

    2. Lynn: run ui_journey_p0_suite_command against the Aaron-certified
       server. Exercises all 12 P0 tools via the qa-smoke tenant against
       pub400.com. Apply Step 5 ticket-filing rules in lynn.md.

    3. Sam: fix only code_bug failures. Ignore env_problem and flaky this
       routine — they belong to Routine 3.

    4. If ≥6 of 12 P0 tools fail in a single run, OR if the same single
       P0 tool fails in TWO consecutive hourly runs: open ONE severity/P0
       issue “P0 SUITE DEGRADATION” in the inova repo instead of 12
       individual tickets. Include the failing tool list.

    5. Write a heartbeat: fleet-workspace/heartbeats/qa-smoke-hourly.txt
       containing the current UTC timestamp. The external watchdog reads
       this; missing heartbeat = silent routine failure.

    Green builds: Ram pushes via normal authority. Do not push if any P0
    ticket is open.
```

---

## How this differs from the earlier Routine 1 spec

The version in `routines-1-2-3.md` tested directly against live
`inovaide.com` and Sam was read-only. This version:

- **Aaron deploys first** — each run gets a freshly deployed local staging
  instance. QA never runs against a stale or broken build.
- **Sam fixes code_bug failures** — up to `max_iterations: 3` fix-and-retest
  cycles before reporting. `env_problem` and `flaky` classifications are
  intentionally skipped here; they route to Routine 3.
- **Ram orchestrates** via the standard agent launch format rather than
  inline STEP 0-N scripting. Ram reads SKILL.md + contexts/inova.md and
  applies its own loop logic.

## Cap accounting

```
R1 hourly smoke   17 runs/day

Team plan (25/day):  68% — leaves 8 slots for R4/R5 webhooks
Max plan  (15/day):  exceeds cap — use Team or Enterprise
Enterprise:          ample headroom
```

If the Team plan cap is a concern on heavy-fix days (R5 firing frequently),
reduce the hourly window (e.g. `5 9-21 * * *` for 13 runs) or move to
Enterprise.

## Heartbeat monitoring

The routine writes `fleet-workspace/heartbeats/qa-smoke-hourly.txt` on
every successful run. An external watchdog checks this file's modification
time; a gap of >70 minutes signals a silent failure (crashed routine,
missed schedule, or hung session).

The watchdog does **not** page on a single missed beat — pub400 maintenance
or a transient platform hiccup causes one natural gap. Page threshold is
two consecutive missed beats (>130 min silence).

## What Ram does when Aaron reports FAILED

Aaron reports `FAILED` when any of these occur:
- Build exits non-zero
- IBMiMCP server fails to register tools within the timeout
- `registered_tool_count < 130`
- Health-check endpoint returns non-2xx

On FAILED, Ram (per human_instructions #1) files ONE issue:

```
title:  Aaron deploy failed
repo:   RSA-Data-Solutions/iNova
labels: qa-bot, platform-failure, severity/P0
body:   Aaron devops report summary + session URL
```

Ram then stops — Lynn and Sam do not run. This prevents false-positive
bug tickets against a deployment that never completed.

## Degradation rule detail (instruction #4)

Ram tracks failure counts across the run and across the previous run
(stored in `fleet-workspace/heartbeats/qa-smoke-hourly-last-failures.json`).

Fire ONE `P0 SUITE DEGRADATION` issue instead of individual tickets when:
- **Broad failure**: ≥6 of the 12 P0 tools fail in this single run
- **Repeat failure**: the exact same single P0 tool appeared in the
  failure list in BOTH this run AND the immediately preceding run

The degradation issue body must include:
- Failing tool list (names + test IDs)
- Whether this is broad or repeat
- Link to both session URLs (this run + prior run for repeat case)
- Timestamp and registered_tool_count from Aaron’s report

Individual tool tickets are NOT filed when the degradation rule fires.
Existing individual open tickets for the same tools remain open.
