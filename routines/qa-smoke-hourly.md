# Routine 1 — Hourly Smoke (P0 suite + deploy) — `qa-smoke-hourly`

## Overview

Hourly P0 smoke run covering all 12 P0 tools. Includes an Aaron
deploy step before QA so the suite always runs against a freshly
deployed build from `main`. Sam fixes code bugs in-loop; env and
flaky failures are left for Routine 3.

---

## Schedule

```
Cron:     5 7-23 * * *
Timezone: UTC
```

Runs at :05 past every hour from 07:05 to 23:05 UTC — 17 runs/day.
Avoids the pub400.com maintenance window (03:00–04:00 UTC).

---

## Cap accounting

```
qa-smoke-hourly  17 runs/day  scheduled
qa-signup-daily   1 run/day   scheduled
qa-explore-daily  1 run/day   scheduled
                 ────────────
total scheduled: 19 runs/day

reserve for:
  qa-release-regression  webhook (event-driven)
  qa-fix-on-issue-open   webhook (event-driven)
```

If you are on a Max plan (15/day) you will exceed the cap on scheduled
runs alone. Enable metered overage in billing settings, or reduce the
window to `7 7-21 * * *` (15 runs) to stay within cap.

---

## Agent launch configuration

```yaml
agent:          agents/ram.md
skill_path:     SKILL.md
context_file:   contexts/inova.md
max_iterations: 3
enable_research: false
```

---

## Prompt (`human_instructions`)

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

## Step-by-step runtime behaviour

### Step 0 — Discover repo paths

```sh
ls -la ~ /workspace 2>/dev/null
```

Identify paths to:
- `always-on-engineering-fleet`
- `iNova`
- `IBMiMCP`

### Step 1 — Read manuals

Read:
```
{fleet}/SKILL.md
{fleet}/agents/ram.md
{fleet}/agents/aaron.md
{fleet}/agents/lynn.md
{fleet}/agents/sam.md
{fleet}/contexts/inova.md
```

### Step 2 — Act as Aaron (deploy + health check)

Deploy the inovaide.com stack from `main`:

```sh
cd {iNova}
git fetch origin main && git checkout main && git pull
docker compose -f docker-compose.dev.yml build
docker compose -f docker-compose.dev.yml up -d
```

Verify IBMiMCP connection:
- Check server health endpoint returns 200
- Confirm `registered_tool_count >= 130`

**If deployment or health check fails:**
- File ONE issue in the `inova` repo:
  - Title: `Aaron deploy failed`
  - Labels: `platform_failure`, `severity/P0`, `qa-bot`
  - Body: include error output and UTC timestamp
- Append `DEPLOY_FAILED` + timestamp to heartbeat file
- **Stop. Do not run QA against a broken build.**

### Step 3 — Act as Lynn (P0 suite)

Run the full P0 suite against the Aaron-certified server:

```sh
cd {iNova}/qa
python3 -m venv .venv && source .venv/bin/activate
pip install -q -r requirements.txt
playwright install --with-deps chromium
QA_HEADLESS=true \
QA_BASE_URL=$QA_BASE_URL \
QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
  python -m pytest ui_journey/test_p0_suite.py -v \
  --json-report --json-report-file=/tmp/p0-report.json
```

**Degradation rule** (evaluate before filing individual tickets):

| Condition | Action |
|-----------|--------|
| ≥6 of 12 P0 tools fail in this run | File ONE `severity/P0` issue `P0 SUITE DEGRADATION` (see below) |
| Same single tool failed last hourly run AND this run | File ONE `severity/P0` issue `P0 SUITE DEGRADATION` |
| <6 tools fail, no repeat single-tool failure | File per-tool tickets per `lynn.md` Step 5 rules |

`P0 SUITE DEGRADATION` issue body must include:
- UTC timestamp
- List of failing tool names
- Failure counts (pass/fail of 12)
- Session URL
- Whether this is a ≥6-failure run or a consecutive-failure pattern

For per-tool ticket filing:
- Apply `lynn.md` Step 5 dedup logic (compute `dedup_hash`, search open issues)
- Labels: `qa-bot`, `severity/Px`, `needs-fix`
- `needs-fix` triggers Routine 5 (Sam auto-fix)

### Step 4 — Act as Sam (code bug fixes only)

For each `code_bug` failure from Lynn's report:
- Read the affected source file(s)
- Apply the smallest fix that makes the test pass
- Re-run the failing test — must pass
- Re-run adjacent tests — must still pass

**Skip** failures classified as `env_problem` or `flaky` — those belong
to Routine 3 (`qa-explore-daily`).

**Do not push** if any P0 ticket is currently open.

### Step 5 — Heartbeat

Write (overwrite) the heartbeat file with the current UTC timestamp:

```sh
date -u +"%Y-%m-%dT%H:%M:%SZ" > {fleet}/fleet-workspace/heartbeats/qa-smoke-hourly.txt
```

Commit and push:

```sh
cd {fleet}
git add fleet-workspace/heartbeats/qa-smoke-hourly.txt
git commit -m "heartbeat: qa-smoke-hourly $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin main
```

The external watchdog (`scripts/watchdog/qa-heartbeat-check.sh`) reads
this file. A missing or stale heartbeat triggers a watchdog alert.

---

## Setup checklist

1. **Create routine** in claude.ai/code/routines:
   - Name: `qa-smoke-hourly`
   - Schedule: `5 7-23 * * *` (UTC)
   - Prompt: paste the `human_instructions` block above

2. **Copy the routine URL and token** from the routines panel into
   GitHub Secrets on this repo:
   - `QA_SMOKE_HOURLY_ROUTINE_URL`
   - `QA_SMOKE_HOURLY_ROUTINE_TOKEN`

3. **Ensure required GitHub secrets exist** on the `inova` repo:
   - `QA_BASE_URL` — staging server base URL
   - `QA_TENANT_SMOKE_PASSWORD` — password for the `qa-smoke` tenant

4. **Verify watchdog** (`scripts/watchdog/qa-heartbeat-check.sh`) is
   pointed at `fleet-workspace/heartbeats/qa-smoke-hourly.txt` and the
   stale threshold matches the hourly cadence (recommend 75 minutes).

5. **Disable `qa-smoke-90min`** once this routine is confirmed healthy
   across 3+ consecutive runs.

---

## Hard limits

| Limit | Value |
|-------|-------|
| Run cap | 20 minutes |
| Max files modified per Sam fix | 5 |
| Max lines changed per Sam fix | 100 |
| Log secrets | Never |
| Touch `baseline_metrics.json` | Never (Routine 4 only) |
| Push if P0 ticket open | Never |
| Push directly to `main` without retest | Never |
