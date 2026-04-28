# Routine 1 — Hourly Smoke (P0 suite + deploy) — `qa-smoke-hourly`

## Schedule

```
Cron:     5 7-23 * * *
Timezone: local (avoids pub400 maintenance window 03:00–04:00 UTC)
```

Runs at :05 past every hour from 07:05 to 23:05.  The pub400.com
maintenance window (03:00–04:00 UTC) falls outside this range.

---

## Ram invocation parameters

| Parameter         | Value                   |
|-------------------|-------------------------|
| `skill_path`      | `SKILL.md`              |
| `context_file`    | `contexts/inova.md`     |
| `max_iterations`  | `3`                     |
| `enable_research` | `false`                 |

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

## Step-by-step inner loop (expanded)

### Step 1 — Aaron: deploy + health check

Aaron deploys the inovaide.com stack from the latest `main` branch of
both the iNova and IBMiMCP repos.

**Pass criteria:**
- Deployment exits without error
- IBMiMCP MCP server responds to health endpoint
- `registered_tool_count >= 130`

**On FAILED deploy:**
- File **ONE** issue in the iNova repo with:
  - Title: `Aaron deploy failed`
  - Label: `platform_failure`, `severity/P0`
  - Body: Aaron's error output, UTC timestamp, session URL
- **Stop immediately** — do not proceed to Lynn or Sam.

### Step 2 — Lynn: P0 suite

Lynn runs `ui_journey_p0_suite_command` against the Aaron-certified
staging server using the `qa-smoke` tenant credentials against
`pub400.com`.

The suite covers **all 12 P0 tools**.

**Ticket-filing rules:** apply Step 5 from `agents/lynn.md`.

Classify each failure as one of:
- `code_bug` — file ticket, add `needs-fix` label
- `env_problem` — log but do **not** file; belongs to Routine 3
- `flaky` — log but do **not** file; belongs to Routine 3

**Degradation escalation:**
- If **≥ 6 of 12** P0 tools fail in this single run, OR
- If the **same single P0 tool** fails in **two consecutive hourly
  runs** (check the previous heartbeat / ticket history):

  → Open **ONE** `severity/P0` issue titled `P0 SUITE DEGRADATION`
    in the iNova repo instead of up to 12 individual tickets.
    Body must include the full list of failing tools.

  → Do **not** open individual tickets for each tool in this case.

### Step 3 — Sam: code_bug fixes only

Sam inspects only failures classified as `code_bug` by Lynn.

- Attempt fixes inline (small, targeted changes only).
- Do **not** attempt to fix `env_problem` or `flaky` — those belong
  to Routine 3.
- Sam follows authority rules in `agents/sam.md`; do not push if
  any P0 ticket is open.

### Step 4 — Heartbeat

After completing the loop (regardless of pass/fail), write the current
UTC timestamp to:

```
fleet-workspace/heartbeats/qa-smoke-hourly.txt
```

Format: one line per run, appended, e.g.:

```
2026-04-28T15:05:03Z  result=green  p0_pass=12/12
2026-04-28T16:05:07Z  result=red    p0_pass=10/12  open_tickets=2
```

Commit and push this file. The external watchdog treats a missing or
stale heartbeat as a silent routine failure.

### Step 5 — Push authority

- **Green build** (zero open P0 tickets): Ram may push code fixes via
  normal authority.
- **Any open P0 ticket**: do **not** push — leave code changes as a
  draft PR for human review.

---

## Hard limits

| Limit                | Value           |
|----------------------|-----------------|
| Max wall-clock time  | 25 minutes      |
| Log secrets          | Never           |
| Touch baseline_metrics.json | Never  |
| Push to main on red  | Never           |

---

## Related files

- `agents/ram.md` — orchestrator instructions
- `agents/aaron.md` — deploy agent
- `agents/lynn.md` — QA agent (Step 5 = ticket-filing rules)
- `agents/sam.md` — fix agent
- `contexts/inova.md` — project context, credentials, URLs
- `SKILL.md` — master operating manual
- `fleet-workspace/heartbeats/qa-smoke-hourly.txt` — watchdog file
