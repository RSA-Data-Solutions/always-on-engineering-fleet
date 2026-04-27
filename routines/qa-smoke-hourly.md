# Routine 1 — Hourly Smoke + Deploy (`qa-smoke-hourly`)

## Metadata

| Field        | Value |
|--------------|-------|
| **Name**     | `qa-smoke-hourly` |
| **Schedule** | `5 7-23 * * *` — :05 past every hour, 07:00–23:00 local time |
| **Repo**     | `RSA-Data-Solutions/always-on-engineering-fleet` |
| **Target**   | Aaron-deployed local staging (`inovaide.com` stack) |

Avoids the pub400 maintenance window (03:00–04:00 UTC) by design —
the cron range stops before it and resumes after.

---

## Agent invocation

Launch **Ram** (`agents/ram.md`) with the following parameters:

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

## Notes

- **Aaron must succeed first.** Steps 2–4 are conditional on a clean
  deploy. If Aaron fails, the single `platform_failure` ticket serves
  as the signal and the run ends — avoids filing false tool-failure
  tickets against a broken build.
- **Sam scope is narrow.** `env_problem` and `flaky` classifications
  are deferred to Routine 3 (daily exploratory) to avoid noisy
  fix branches from transient failures.
- **Degradation guard** fires on either threshold (breadth: ≥6/12 in
  one run, or depth: same tool fails across two consecutive runs).
  The consolidated P0 issue replaces all individual per-tool tickets.
- **Heartbeat** at `fleet-workspace/heartbeats/qa-smoke-hourly.txt`
  is the external watchdog signal. A missing heartbeat means the
  routine ran silently or not at all.
- **No push on open P0.** Ram's green-build push gate is blocked while
  any P0 issue is open, preventing stale code from being promoted.
