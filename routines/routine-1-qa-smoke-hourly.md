# Routine 1 — Hourly Smoke (P0 suite + deploy) — `qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (Central Time)
```

Runs at :05 past every hour from 07:00 to 23:00 local time — 17 runs/day.
Avoids pub400 maintenance window (03:00–04:00 UTC).

## One-time setup

**Three repos attached:**
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

**GitHub connector:** issues:write + PR access on all three repos.

**Environment variables** (set in the routine's settings panel, NOT in the prompt):
- `QA_BASE_URL` = `https://inovaide.com`
- `QA_TENANT_SMOKE_PASSWORD` = (qa-smoke@inovaide-qa.com password)

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
       connection is healthy and registered_tool_count >= 130. If Aaron
       reports FAILED, file ONE platform_failure ticket titled "Aaron
       deploy failed" and stop -- do not run QA against a broken build.

    2. Lynn: run ui_journey_p0_suite_command against the Aaron-certified
       server. Exercises all 12 P0 tools via the qa-smoke tenant against
       pub400.com. Apply Step 5 ticket-filing rules in lynn.md.

    3. Sam: fix only code_bug failures. Ignore env_problem and flaky this
       routine -- they belong to Routine 3.

    4. If >=6 of 12 P0 tools fail in a single run, OR if the same single
       P0 tool fails in TWO consecutive hourly runs: open ONE severity/P0
       issue "P0 SUITE DEGRADATION" in the inova repo instead of 12
       individual tickets. Include the failing tool list.

    5. Write a heartbeat: fleet-workspace/heartbeats/qa-smoke-hourly.txt
       containing the current UTC timestamp. The external watchdog reads
       this; missing heartbeat = silent routine failure.

    Green builds: Ram pushes via normal authority. Do not push if any P0
    ticket is open.
```

## Heartbeat

Each run appends a UTC timestamp line to
`fleet-workspace/heartbeats/qa-smoke-hourly.txt` and commits it to the
fleet repo. The external watchdog monitors this file; a missing or stale
heartbeat indicates a silent routine failure.

## Key differences from the older `qa-smoke-90min` spec

| Dimension | qa-smoke-90min (routines-final.md) | qa-smoke-hourly (this file) |
|-----------|------------------------------------|--------------------------|
| Schedule | Every 90 min, 11 runs/day | Every 60 min, 17 runs/day |
| Deploy step | None — tests live site as-is | Aaron deploys latest main first |
| Sam role | Read-only (triage only) | Fixes code_bug class failures |
| Degradation threshold | Same tool fails this AND prev run | Same tool fails in TWO consecutive runs |
| Push authority | Not mentioned | Ram pushes on green; blocked if any P0 open |
| max_iterations | Not set | 3 |

## Cap accounting (Team plan, 25 runs/day)

```
R1 hourly smoke      17 runs/day  (68%)
R2 signup daily       1 run/day   (4%)
R3 explore daily      1 run/day   (4%)
R4 post-deploy        webhook (variable)
                     ─────────────
total scheduled:     19 runs/day  (76%)
```

Leaves ~6 slots/day for Routine 4 webhook fires and manual runs before
hitting the 25/day cap. On heavy-deploy days with multiple Routine 4
fires, enable metered overage in billing settings.
