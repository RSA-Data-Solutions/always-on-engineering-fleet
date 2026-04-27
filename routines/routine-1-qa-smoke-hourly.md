# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

**Name:** `qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local
```

Runs at :05 past every hour from 07:00 to 23:00 local time.  
Avoids pub400 maintenance window (03:00–04:00 UTC).

---

## Agent invocation

Launch the Ram agent (`agents/ram.md`) with:

```yaml
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

  4. If >= 6 of 12 P0 tools fail in a single run, OR if the same single
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

## Inner loop detail

### Step 1 — Aaron: deploy + health check

- Deploy the inovaide.com stack from the latest `main` branch.
- Verify IBMiMCP connection is healthy and `registered_tool_count >= 130`.
- **On FAILED:** file exactly **one** `platform_failure` issue titled  
  `"Aaron deploy failed"` and halt — do not proceed to QA against a
  broken build.

### Step 2 — Lynn: P0 suite

- Run `ui_journey_p0_suite_command` against the Aaron-certified server.
- Tenant: `qa-smoke`; backend: `pub400.com`.
- Covers all 12 P0 tools.
- Apply Step 5 ticket-filing rules from `agents/lynn.md` for every
  failure found.

### Step 3 — Sam: targeted fix

- Fix **only** `code_bug` failures surfaced by Lynn.
- **Skip** `env_problem` and `flaky` failures — those belong to Routine 3.
- Sam operates within the standard `max_iterations: 3` budget.

### Step 4 — Degradation gate

Before filing individual tickets, evaluate:

| Condition | Action |
|-----------|--------|
| >= 6 of 12 P0 tools fail in this run | Open **one** `severity/P0` issue `"P0 SUITE DEGRADATION"` listing all failing tools; skip individual tickets |
| The same single P0 tool failed in this run AND the previous hourly run | Same — open the single `"P0 SUITE DEGRADATION"` issue instead |

### Step 5 — Heartbeat

Write current UTC timestamp to:

```
fleet-workspace/heartbeats/qa-smoke-hourly.txt
```

Commit and push. The external watchdog monitors this file; if it goes
stale the watchdog raises a silent-failure alert.

### Push gate

Ram uses normal push authority **only when**:
- The suite is green (zero new tickets), AND
- No `severity/P0` ticket is currently open in the inova repo.

Do not push if any P0 ticket is open.

---

## Hard limits

| Limit | Value |
|-------|-------|
| Run cap | 20 minutes |
| Sam fix budget | `max_iterations: 3` |
| Push gate | No P0 tickets open |
| Secrets in logs | Never |
| Baseline metrics | Do NOT touch `baseline_metrics.json` |

---

## Heartbeat file

**Path:** `fleet-workspace/heartbeats/qa-smoke-hourly.txt`  
**Format:** one UTC timestamp per line, appended each run.

Example:
```
2026-04-27T08:05:42Z
2026-04-27T09:05:38Z
2026-04-27T10:05:51Z
```

---

## Related routines

| Routine | Name | Purpose |
|---------|------|---------|
| 2 | `qa-signup-daily` | Daily new-tenant signup flow |
| 3 | `qa-explore-daily` | Daily exploratory / env_problem triage |
| 4 | `qa-release-regression` | Post-deploy regression (webhook) |
| 5 | `qa-fix-on-issue-open` | Sam auto-fix on P0/P1 issue label (webhook) |

See `routines/routines-final.md` for the full routine plan and cap accounting.
