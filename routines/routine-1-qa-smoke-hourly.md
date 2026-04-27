# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

**Name:** `qa-smoke-hourly`
**Schedule:** `5 7-23 * * *` — runs at :05 past every hour from 07:00 to 23:00 local time. Avoids pub400 maintenance (03:00–04:00 UTC).
**Repo:** `RSA-Data-Solutions/always-on-engineering-fleet`
**Target:** Aaron-deployed local staging

---

## Setup

**Repos to attach:**
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

**Environment variables (set in routine env panel, not the prompt):**
- `QA_BASE_URL` — staging URL Aaron deploys to
- `QA_TENANT_SMOKE_PASSWORD` — qa-smoke tenant password

**GitHub connector:** issues:write + PR access on all three repos.

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
       connection is healthy and registered_tool_count >= 130. If Aaron
       reports FAILED, file ONE platform_failure ticket titled "Aaron
       deploy failed" and stop — do not run QA against a broken build.

    2. Lynn: run ui_journey_p0_suite_command against the Aaron-certified
       server. Exercises all 12 P0 tools via the qa-smoke tenant against
       pub400.com. Apply Step 5 ticket-filing rules in lynn.md.

    3. Sam: fix only code_bug failures. Ignore env_problem and flaky this
       routine — they belong to Routine 3.

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

---

## Agent roles summary

| Agent | Role in this routine |
|-------|---------------------|
| Ram | Orchestrator — reads SKILL.md + contexts/inova.md, coordinates Aaron → Lynn → Sam |
| Aaron | Deploy staging from latest main; verify IBMiMCP health (registered_tool_count ≥ 130) |
| Lynn | Run P0 suite; file tickets per lynn.md Step 5 rules |
| Sam | Fix code_bug failures only; skip env_problem and flaky |

---

## Degradation rules

- **Broad failure:** ≥6 of 12 P0 tools fail in a single run → file ONE `severity/P0` issue `"P0 SUITE DEGRADATION"` in iNova repo listing all failing tools. Do NOT file 12 individual tickets.
- **Repeat failure:** same single P0 tool fails in TWO consecutive hourly runs → also file ONE `severity/P0` `"P0 SUITE DEGRADATION"` issue (not an individual tool ticket).

---

## Heartbeat

The routine writes `fleet-workspace/heartbeats/qa-smoke-hourly.txt` with the current UTC timestamp at the end of each run. The external watchdog monitors this file; a missing or stale heartbeat signals a silent routine failure.

---

## Push authority

Ram may push code fixes (via Sam) only on **green builds** — i.e. when no P0 ticket is open at the end of the run. If any P0 ticket is open (including a freshly filed one), Ram does **not** push.

---

## Cap accounting

```
R1 qa-smoke-hourly  17 runs/day  (68% of 25-run Team plan cap)
                                  leaves headroom for R4 webhook fires
```

Cron `5 7-23 * * *` fires at :05 past each of the 17 hours 07–23 local time.  
This is equivalent to the UTC cron `5 12-4 * * *` when running Central Time (UTC-5/-6).
