# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

**Name:** `qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

Runs at :05 past every hour from 07:00–23:00 local time.
Avoids the pub400.com maintenance window (03:00–04:00 UTC).

---

## Agent Launch

Launch `agents/ram.md` with:

```yaml
skill_path:         SKILL.md
context_file:       contexts/inova.md
max_iterations:     3
enable_research:    false
```

---

## Prompt

```
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

## Degradation Rules (expanded)

| Condition | Action |
|-----------|--------|
| ≥ 6 of 12 P0 tools fail in one run | Open one `severity/P0` issue "P0 SUITE DEGRADATION" with full failing-tool list; skip individual tickets |
| Same single P0 tool fails in **two consecutive** hourly runs | Open one `severity/P0` issue "P0 SUITE DEGRADATION"; include tool name and both run timestamps |
| Aaron deploy fails | File one `platform_failure` ticket "Aaron deploy failed"; stop — do not run QA |
| Any P0 ticket is open | Ram does **not** push, even if current suite is green |

---

## Heartbeat

File: `fleet-workspace/heartbeats/qa-smoke-hourly.txt`

Content: current UTC timestamp, appended each run.

The `scripts/watchdog/qa-heartbeat-check.sh` monitors this file.
A missing or stale heartbeat signals a silent routine failure and
will page the on-call operator.

---

## Notes

- **enable_research: false** — smoke runs never spawn Dhira.
- **max_iterations: 3** — Sam gets at most 3 fix/retest cycles before
  Ram declares the run done and files any open failures.
- env_problem and flaky failures are **not** actioned in this routine;
  they are caught by Routine 3 (daily exploratory).
- The `ui_journey_p0_suite_command` is defined in `contexts/inova.md`
  and executed by Lynn from the iNova repo's `qa/` directory.
