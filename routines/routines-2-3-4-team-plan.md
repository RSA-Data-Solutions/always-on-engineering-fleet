# Routines 2, 3 & 4 — Team Plan (25 runs/day)

Authoritative prompt and schedule specifications for Routines 2, 3, and 4
under the Team plan. Supersedes the matching stubs in `routines-final.md`
(which targeted Max plan, 15 runs/day).

---

## Cap accounting (Team plan, 25 routine runs/day)

| Routine | Runs/day | Cap used |
|---|---|---|
| 1. Hourly smoke | 17 (07:00–23:00) | 68% |
| 2. Signup daily | 1 | 4% |
| 3. Explore daily | 1 | 4% |
| 4. Post-deploy | variable (webhook) | metered overage |

**Scheduled total: 76% of Team cap (19 of 25 runs).**

Enable metered overage in Settings → Billing before heavy deploy days.
Pro plan is insufficient; Max is tight (76% × 15 = 11 of 15 reserved for
scheduled work); **Team or Enterprise recommended**.

---

## Routine 2 — Daily signup + first-run UX

**Name:** `qa-signup-daily`  
**Schedule:** `0 2 * * *` local time  
**Target URL:** `https://inovaide.com` (PROD — catches cert/email/DNS rot invisible in staging)

### Prompt

```
Launch Ram with:

  skill_path:         SKILL.md
  context_file:       contexts/inova.md
  max_iterations:     2
  enable_research:    false
  human_instructions: |
    Daily signup regression against PROD inovaide.com. No Aaron — we're not
    deploying, we're testing the live site.

    Lynn: generate a fresh email using the qa_tenants.signup_bot template
    (qa+{unix_timestamp}@inovaide-qa.com). Run ui_journey_signup_command.
    Required flow, each step timed:

      land → signup form → submit → email verify → first-login →
      VS Code boot → OpenCode CLI visible → IBMiMCP tools listed →
      first tool call (listTables) returns success

    Step thresholds (from qa/baseline_metrics.json):
      - Any step >threshold         → severity/P1 ticket
      - Any step fails outright     → severity/P0 ticket
      - Signup email >180s delayed  → severity/P1 (not a flake above threshold)

    All tickets route to inova (platform_failure) since the signup surface
    is owned there — even if the first tool call fails, that's a platform
    issue here because the journey didn't complete.

    Do not delete the created account. Do not reuse it either. A separate
    weekly GC routine prunes old signup_bot accounts.

    Heartbeat: fleet-workspace/heartbeats/qa-signup-daily.txt
```

---

## Routine 3 — Daily exploratory + rotation

**Name:** `qa-explore-daily`  
**Schedule:** `0 5 * * *` local time (after maintenance window)  
**Target URL:** Aaron-deployed local staging

### Prompt

```
Launch Ram with:

  skill_path:         SKILL.md
  context_file:       contexts/inova.md
  max_iterations:     5
  enable_research:    true
  human_instructions: |
    Daily deep QA run. Two phases.

    PHASE A — Dhira (research, ~30 min budget):
      Search IBM i communities (code400.com, r/IBMi, IBM i OSS Slack,
      #IBMiOSS on X) AND the issue trackers of both repos for complaints
      filed in the last 24h that aren't already covered.
      Write proposals to fleet-workspace/proposals/YYYY-MM-DD-*.md.
      These are FLEET PROPOSALS for CTO review — do NOT file them as
      customer tickets. One proposal per distinct pain pattern.

    PHASE B — Lynn (rotation):
      Aaron certifies the server. Run ui_journey_rotation_command. The
      --rotation-day flag picks today's batch from rotation_batches in
      contexts/inova.md based on $(date +%A).

      For each tool in the batch:
        - Use golden input from test_rotation.py if defined
        - Otherwise improvise from the tool's inputSchema — pick a
          read-only operation with defensive defaults
        - Record success/failure, latency, response shape

      Apply Step 5 ticket-filing rules in lynn.md. Be ruthless on
      classification: exploratory is where noise lives. If the repro
      isn't crisp in 3 lines, it's not a ticket — it's a Dhira proposal.

    Sam fixes only failures Ram explicitly approves this iteration.

    Heartbeat: fleet-workspace/heartbeats/qa-explore-daily.txt
```

---

## Routine 4 — Post-deploy regression (webhook)

**Name:** `qa-release-regression`  
**Schedule:** none — webhook-triggered  
**Trigger:** `/fire` endpoint, called from the `release-qa.yml` GitHub Action
on push to `main` in either `RSA-Data-Solutions/inova` or `RSA-Data-Solutions/IBMiMCP`.

The workflow file lives at `.github/workflows/release-qa.yml` in both repos.
Add `ANTHROPIC_API_KEY_QA` as a repository secret in each repo
(Settings → Secrets and variables → Actions) before enabling.

### GitHub Action (`release-qa.yml`)

```yaml
name: Fire QA regression routine
on:
  push:
    branches: [main]

jobs:
  fire-qa:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger QA regression routine
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY_QA }}
        run: |
          curl -X POST https://api.anthropic.com/v1/code/routines/qa-release-regression/fire \
            -H "x-api-key: $ANTHROPIC_API_KEY" \
            -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
            -H "Content-Type: application/json" \
            -d '{
              "inputs": {
                "source_repo": "${{ github.repository }}",
                "commit_sha": "${{ github.sha }}",
                "commit_timestamp": "${{ github.event.head_commit.timestamp }}",
                "author": "${{ github.event.head_commit.author.name }}"
              }
            }'
```

### Prompt

Ram is launched via the `/fire` API. Parameters:

    skill_path:         SKILL.md
    context_file:       contexts/inova.md
    max_iterations:     8
    enable_research:    false

human_instructions (template variables interpolated at fire time):

    Post-deploy regression for {{ inputs.commit_sha }} from {{ inputs.source_repo }}
    (authored by {{ inputs.author }} at {{ inputs.commit_timestamp }}).

    1. Aaron: deploy the EXACT commit {{ inputs.commit_sha }} from
       {{ inputs.source_repo }}. Verify IBMiMCP connection and
       registered_tool_count. If Aaron reports FAILED, file ONE
       release-blocker issue titled "Build {{ inputs.commit_sha }}
       failed to deploy" in {{ inputs.source_repo }} and stop.

    2. Lynn: run the FULL suite:
         - test_command (orchestrator pytest)
         - ui_journey_test_command (all P0 + all 7 rotation batches)
       Diff P95 latencies against qa/baseline_metrics.json.

    3. Tickets filed by this routine get an ADDITIONAL label:
       `release-blocker`. Severity rules:
         - Any P0 tool regression >20% on P95         → severity/P0 + release-blocker
         - Any P0 tool functionally broken             → severity/P0 + release-blocker
         - >10% of non-P0 tools regressing >30%        → severity/P1 + release-blocker
         - Signup/VS Code/OpenCode broken              → severity/P0 + release-blocker

    4. If suite passes clean: Ram updates qa/baseline_metrics.json with
       the new P95s (one PR against the inova repo) and merges. Do NOT
       update the baseline if anything failed — keep the prior bar so
       the next fix measures against pre-regression numbers.

    5. Heartbeat: fleet-workspace/heartbeats/qa-release-{{ inputs.commit_sha[:8] }}.txt

---

## Watchdog (external, runs on homelab)

The watchdog runs every 15 minutes on a machine **separate from inovaide.com**
and emails on silence. A missing or stale heartbeat means the fleet is dead.
Treat any watchdog alert as `severity/P1` — you're flying blind until fixed.

### Cron entry (`/etc/cron.d/qa-fleet-watchdog`)

    */15 * * * * sashi /usr/local/bin/qa-heartbeat-check.sh

### Script

Full script: `scripts/qa-heartbeat-check.sh` in this repository.  
Copy to `/usr/local/bin/qa-heartbeat-check.sh` on the homelab, `chmod +x` it,
and update the `FLEET_DIR` variable to point to your local clone.

| Heartbeat file | Max age | Alert when... |
|---|---|---|
| `qa-smoke-hourly.txt` | 2 h (7 200 s) | Smoke routine silent |
| `qa-signup-daily.txt` | 36 h (129 600 s) | Daily signup silent |
| `qa-explore-daily.txt` | 36 h (129 600 s) | Daily explore silent |
