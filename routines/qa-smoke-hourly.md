# Routine 1 — Hourly Smoke (P0 suite + deploy)

**Name:** `qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

Runs at :05 past every hour from 07:00–23:00 local time.
Avoids pub400.com maintenance window (03:00–04:00 UTC).

## Purpose

Hourly heartbeat that:
1. Aaron deploys the inovaide.com stack from latest main and verifies IBMiMCP health.
2. Lynn runs the full P0 suite (12 tools) via the `qa-smoke` tenant against pub400.com.
3. Sam patches `code_bug` failures in-session (env_problem / flaky deferred to Routine 3).
4. Escalates to a single "P0 SUITE DEGRADATION" issue when the suite is broadly broken.
5. Writes a heartbeat file so the external watchdog can detect silent failures.

## Prompt

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

## Cap accounting

```
Runs/day:   17  (07:05 – 23:05, one per hour)
Cap usage:  17 of 15 (Max plan) → enable metered overage or reduce window
```

> **Note:** 17 runs/day exceeds the 15/day Max plan cap. Either enable
> metered overage in billing settings, or narrow the cron window
> (e.g. `5 8-22 * * *` for 15 runs/day) before activating.

## Heartbeat file

Each successful run appends a UTC timestamp to:

```
fleet-workspace/heartbeats/qa-smoke-hourly.txt
```

The external watchdog alerts if this file is not updated within 75 minutes.

## Escalation thresholds

| Condition | Action |
|-----------|--------|
| Aaron deploy FAILED | File 1× `platform_failure` ticket "Aaron deploy failed"; stop run |
| ≥6 of 12 P0 tools fail in one run | File 1× `severity/P0` issue "P0 SUITE DEGRADATION" instead of individual tickets |
| Same single P0 tool fails in 2 consecutive runs | File 1× `severity/P0` issue "P0 SUITE DEGRADATION" |
| Any P0 ticket open | Ram does NOT push green-build commits |

## Related routines

| Routine | Name | Purpose |
|---------|------|---------|
| Routine 3 | `qa-explore-daily` | Handles env_problem + flaky failures ignored here |
| Routine 4 | `qa-release-regression` | Full regression on push to main |
| Routine 5 | `qa-fix-on-issue-open` | Sam auto-fix triggered by needs-fix label |
