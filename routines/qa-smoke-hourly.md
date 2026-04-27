# Routine 1 — Hourly Smoke (P0 Suite + Deploy)

**Slug:** `qa-smoke-hourly`  
**Repo:** `RSA-Data-Solutions/always-on-engineering-fleet`  
**Target:** Aaron-deployed local staging → inovaide.com P0 suite against pub400.com

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (server-local)
```

Runs at :05 past every hour from **07:00 to 23:00** local time — 17 runs/day.
Avoids the **03:00–04:00 UTC** pub400 maintenance window.

---

## One-time setup

The routine needs three repos attached:
- `RSA-Data-Solutions/always-on-engineering-fleet`
- `RSA-Data-Solutions/iNova`
- `RSA-Data-Solutions/IBMiMCP`

GitHub connector with `issues:write` + PR access on all three.

Environment variables (set in the routine's env panel, NOT in the prompt):

| Variable | Value |
|----------|-------|
| `QA_BASE_URL` | `https://inovaide.com` |
| `QA_TENANT_SMOKE_PASSWORD` | qa-smoke@inovaide-qa.com password |
| `QA_BYPASS_SECRET` | HMAC bypass secret from iNova `.env` |

---

## Prompt

Paste exactly into the routine's prompt field in `claude.ai/code/routines`:

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

## Behaviour notes

### Aaron gate (Step 1)
Ram invokes Aaron first. If Aaron's deploy fails or `registered_tool_count < 130`,
the routine files a single `platform_failure` ticket titled **"Aaron deploy failed"**
and exits immediately — no QA runs against a broken build.

### P0 suite (Step 2)
Lynn runs `ui_journey_p0_suite_command` — the canonical 12-tool P0 suite — against
the Aaron-certified server using the `qa-smoke` tenant and pub400.com credentials.
Ticket-filing follows the Step 5 rules in `agents/lynn.md` (dedup hash, severity label,
`qa-bot` label).

### Sam scope (Step 3)
Sam may fix **`code_bug`** failures only. `env_problem` and `flaky` classifications
are explicitly deferred to Routine 3 (daily exploratory), which is designed to handle
environment churn. This keeps hourly smoke fast and low-noise.

### Degradation rule (Step 4)
Instead of filing up to 12 individual tickets, Ram triggers the degradation path when:
- **≥ 6 of 12 P0 tools fail in a single run**, OR
- **The same single P0 tool fails in two consecutive hourly runs**

In either case, Ram opens exactly ONE `severity/P0` issue titled **"P0 SUITE DEGRADATION"**
in the iNova repo, listing all failing tools. This caps noise and signals a systemic
problem rather than isolated bugs.

### Heartbeat (Step 5)
Every run (including runs with failures) must append a UTC ISO-8601 timestamp to
`fleet-workspace/heartbeats/qa-smoke-hourly.txt` and push to the fleet repo.
The external watchdog reads this file on a regular interval; a missing or stale
heartbeat triggers an alert independently of GitHub issue state.

### Push authority
Ram pushes green builds directly (normal authority). Ram **does not push** if any P0
ticket remains open at end of the run.

---

## Cap accounting

```
qa-smoke-hourly     17 runs/day  (68% of Team plan 25/day cap)
qa-signup-daily      1 run/day   ( 4%)
qa-explore-daily     1 run/day   ( 4%)
qa-release-*         webhook      (variable — metered overage)
                    ────────────
total scheduled:    19 runs/day  (76%)
```

Team plan (25/day) is the floor. Pro (5/day) and Max (15/day) cannot
accommodate this schedule.

---

## Heartbeat file

`fleet-workspace/heartbeats/qa-smoke-hourly.txt`

Format: one UTC ISO-8601 timestamp per line, appended each run.
The watchdog alerts if the most recent line is older than 90 minutes.

---

## Relationship to other routines

| Routine | Slug | Trigger | Scope |
|---------|------|---------|-------|
| **1 — Hourly Smoke** | `qa-smoke-hourly` | `5 7-23 * * *` | P0 suite + Aaron deploy |
| 2 — Daily Signup | `qa-signup-daily` | `0 8 * * *` | Fresh-account signup journey |
| 3 — Daily Exploratory | `qa-explore-daily` | `0 11 * * *` | Dhira research + rotation batch |
| 4 — Post-Deploy | `qa-release-regression` | webhook (push to main) | Full regression + baseline update |
| 5 — Sam Auto-Fix | `qa-fix-on-issue-open` | webhook (issue labeled) | Sam proposes fix PR |

Routine 3 handles `env_problem` and `flaky` failures that Routine 1 deliberately skips.
Routine 4 runs the authoritative full regression and is the only routine that updates
`baseline_metrics.json`.
