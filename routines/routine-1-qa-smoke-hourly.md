# Routine 1 — Hourly P0 Smoke + Deploy

**Name:** `qa-smoke-hourly`
**Schedule:** `5 7-23 * * *` (runs at :05 past every hour, 07:05–23:05 local time; avoids pub400 maintenance window 03:00–04:00 UTC)
**Repo:** `RSA-Data-Solutions/always-on-engineering-fleet`

---

## What this routine does

Every hour during working hours this routine:

1. Has **Aaron** deploy the latest `main` of the inovaide.com stack and verify the IBMiMCP connection is healthy.
2. Has **Lynn** run the full 12-tool P0 smoke suite against the freshly-deployed server.
3. Has **Sam** fix any `code_bug` failures in place.
4. Applies a **suite-degradation rule** to avoid ticket spam on catastrophic failures.
5. Writes a **heartbeat file** so the external watchdog can detect silent routine failures.

---

## Schedule

```
Cron:      5 7-23 * * *
Timezone:  local (server time)
```

Runs 17 times per day (07:05, 08:05, … 23:05). The cron expression excludes
00:05–06:05 local time, which covers the pub400.com maintenance window.

---

## Ram invocation parameters

| Parameter | Value |
|-----------|-------|
| `skill_path` | `SKILL.md` |
| `context_file` | `contexts/inova.md` |
| `max_iterations` | `3` |
| `enable_research` | `false` |
| `human_instructions` | *(see below)* |

---

## Prompt (`human_instructions`)

```
Hourly P0 smoke. Inner loop:

1. Aaron: deploy inovaide.com stack from latest main. Verify IBMiMCP
   connection is healthy and registered_tool_count >= 130. If Aaron
   reports FAILED, file ONE platform_failure ticket titled
   "Aaron deploy failed" and stop — do not run QA against a broken build.

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

## Step-by-step detail

### Step 1 — Aaron: deploy and verify

Spawn **Aaron** (`agents/aaron.md`) with:
- `repo_path` from `contexts/inova.md`
- `git_ref`: latest `main`
- `endpoint_smoke_tests`: IBMiMCP health check + `registered_tool_count` probe
- `output_path`: `fleet-workspace/heartbeats/aaron-deploy-latest.json`

Read `overall_status` from the devops report:
- `READY` → continue to Step 2.
- `FAILED` → file **one** GitHub issue in the iNova repo:
  - Title: `Aaron deploy failed`
  - Labels: `platform_failure`, `severity/P0`
  - Body: Aaron's error output + timestamp + session URL
  - **Stop the routine here.** Do not run QA against a broken build.

If `registered_tool_count < 130` even when overall status is `READY`, treat
it as `FAILED` (IBMiMCP is partially registered; QA results would be
unreliable).

### Step 2 — Lynn: run the P0 suite

Spawn **Lynn** (`agents/lynn.md`) with:
- `server_already_running: true` (Aaron started it in Step 1)
- `test_command`: `ui_journey_p0_suite_command` (defined in `contexts/inova.md`)
- `tenant`: `qa-smoke`
- `pub400_host`: `pub400.com`
- `output_path`: `fleet-workspace/iteration-N/qa-report.json`

Lynn exercises all 12 P0 tools and applies Step 5 ticket-filing rules from
`lynn.md` (dedup hash, open-issue search, label assignment).

### Step 3 — Sam: fix code_bug failures only

- Sam **only acts on** failures whose `failure_type == "code_bug"`.
- `env_problem` and `flaky` failures are logged in the QA report but **no
  fix is attempted** and **no ticket is filed** by this routine — they are
  handled by Routine 3 (daily exploratory).
- Sam follows the normal fix loop: diagnose → smallest fix → retest →
  confirm no regressions.

### Step 4 — Degradation detection

After Lynn's report is collected, apply these rules **before** filing
individual tickets:

| Condition | Action |
|-----------|--------|
| `>=6` of 12 P0 tools failed in **this** run | Open **one** `severity/P0` issue `"P0 SUITE DEGRADATION"` listing all failing tools. Skip individual tickets. |
| The **same** single P0 tool failed in **this** run AND in the **previous** hourly run | Open **one** `severity/P0` issue `"P0 SUITE DEGRADATION"` for that tool. Skip its individual ticket. |
| Otherwise | File normal per-tool tickets per `lynn.md` Step 5 rules. |

To detect the consecutive-failure condition, read the previous run's
`qa-report.json` from `fleet-workspace/heartbeats/qa-smoke-last-report.json`
(written at end of each run, see Step 5). Compare failing tool lists.

### Step 5 — Heartbeat + last-report snapshot

1. Append the current UTC timestamp to
   `fleet-workspace/heartbeats/qa-smoke-hourly.txt`:
   ```
   2026-04-26T08:05:01Z  pass=10 fail=2 fixed=1
   ```
2. Copy the current `qa-report.json` to
   `fleet-workspace/heartbeats/qa-smoke-last-report.json`
   (overwrites; used by Step 4 next hour).
3. Commit and push both files.

### Push / no-push rule

- **Push** (Sam's fixes + heartbeat) if: no P0 tickets are currently open in
  the iNova repo AND the targeted failing tests now pass AND no regressions.
- **Do not push** if any `severity/P0` issue is open in the iNova repo at
  the time of push evaluation (degradation or Aaron failure).
- Heartbeat is **always** written and pushed regardless of test outcome so
  the watchdog can distinguish "routine ran but tests failed" from "routine
  never ran".

---

## Outputs

| File | Purpose |
|------|---------|
| `fleet-workspace/heartbeats/qa-smoke-hourly.txt` | Append-only timestamp log; watchdog liveness signal |
| `fleet-workspace/heartbeats/qa-smoke-last-report.json` | Snapshot of last run's QA report; used for consecutive-failure detection |
| `fleet-workspace/heartbeats/aaron-deploy-latest.json` | Aaron's devops report from the most recent deploy |
| `fleet-workspace/iteration-N/qa-report.json` | Lynn's full P0 suite report |

---

## Failure modes and expected behaviour

| Scenario | Outcome |
|----------|---------|
| Aaron deploy fails | ONE `platform_failure` ticket, routine stops, heartbeat still written |
| `registered_tool_count < 130` | Treated as Aaron FAILED (see above) |
| 1–5 P0 tools fail, not consecutive | Individual tickets per `lynn.md` Step 5 |
| >=6 P0 tools fail | ONE `P0 SUITE DEGRADATION` ticket, no individual tickets |
| Same tool fails two runs in a row | ONE `P0 SUITE DEGRADATION` ticket for that tool |
| Sam cannot reproduce/fix | `needs-human-review` label added; no push |
| Routine crashes before heartbeat | Watchdog fires (missing timestamp in heartbeat file) |

---

## Cap accounting

At 17 runs/day this routine uses the bulk of any daily run budget.
Other routines (Routine 2, 3, 4, 5) should be budgeted against the
remainder. See `routines/routines-final.md` for the full cap plan.
