# Routine 1 — Hourly Smoke (P0 suite + deploy)

## Overview

| Field        | Value                                                                 |
|--------------|-----------------------------------------------------------------------|
| **Name**     | `qa-smoke-hourly`                                                     |
| **Schedule** | `5 7-23 * * *` — :05 past every hour, 07:00–23:00 local time         |
| **Repos**    | `RSA-Data-Solutions/always-on-engineering-fleet`, `RSA-Data-Solutions/iNova`, `RSA-Data-Solutions/IBMiMCP` |
| **Target**   | Aaron-deployed local staging                                          |
| **Heartbeat**| `fleet-workspace/heartbeats/qa-smoke-hourly.txt`                      |

The cron is expressed in local server time; the window is chosen to avoid
the pub400 maintenance window (03:00–04:00 UTC). At 17 runs/day this uses
~68% of a Team plan cap, leaving headroom for Routine 4 webhook fires.

---

## Repos required

Attach all three repos to this routine in the routine settings panel:

- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

GitHub connector needs `issues:write` + PR access on all three.

---

## Environment variables (set in the routine's env panel — NOT in the prompt)

| Variable                    | Description                                    |
|-----------------------------|------------------------------------------------|
| `QA_BASE_URL`               | Aaron-deployed staging URL for this run        |
| `QA_TENANT_SMOKE_PASSWORD`  | Password for `qa-smoke@inovaide-qa.com`        |

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (server)
```

Runs at :05 past every hour from 07:00 to 23:00.
Avoids pub400 maintenance window (03:00–04:00 UTC).

---

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

---

## Degradation rule (summary)

| Condition                                                  | Action                                                                              |
|------------------------------------------------------------|-------------------------------------------------------------------------------------|
| ≥ 6 of 12 P0 tools fail in one run                        | File ONE `severity/P0` issue "P0 SUITE DEGRADATION" (not individual tickets)        |
| Same single P0 tool fails in TWO consecutive hourly runs   | File ONE `severity/P0` issue "P0 SUITE DEGRADATION" listing the tool                |
| Aaron deploy fails                                         | File ONE `platform_failure` ticket "Aaron deploy failed" and stop immediately        |

---

## Heartbeat

At the end of every run (pass or fail), Ram must append the current UTC
ISO timestamp to:

```
fleet-workspace/heartbeats/qa-smoke-hourly.txt
```

and push the commit. The external watchdog checks this file. A missing
or stale heartbeat (older than ~90 min) triggers a silent-failure alert.

---

## Hard limits

- Total run time cap: **20 minutes**. If exceeded, file ONE `severity/P1`
  issue "Routine 1 timed out at {step}" in the iNova repo and stop.
- Never commit secrets, passwords, or QA bypass tokens.
- Do NOT touch `baseline_metrics.json` — only Routine 4 updates it.
- Sam must NOT push fixes from this routine if any P0 ticket is open.
- Sam scope this routine: **code_bug only**. `env_problem` and `flaky`
  failures belong to Routine 3 and must not be actioned here.

---

## Cap accounting (Team plan, 25 runs/day)

```
R1 qa-smoke-hourly   17 runs/day  (68%)
R2 qa-signup-daily    1 run/day   (4%)
R3 qa-explore-daily   1 run/day   (4%)
R4 post-deploy        webhook — variable, metered overage
R5 fix-on-issue       webhook — variable, metered overage
                     ─────────────────────────────────────
total scheduled:     19 runs/day  (76%)
reserve (R4 + R5):    6 runs/day  (24%)
```

---

## Related routines

| Routine | Name                   | Handles                                           |
|---------|------------------------|---------------------------------------------------|
| R2      | `qa-signup-daily`      | Fresh-signup regression, daily                    |
| R3      | `qa-explore-daily`     | Exploratory rotation + `env_problem`/`flaky` triage |
| R4      | `qa-release-regression`| Post-deploy full regression, webhook-triggered    |
| R5      | `qa-fix-on-issue-open` | Sam auto-fix on P0/P1 issues, webhook-triggered   |
