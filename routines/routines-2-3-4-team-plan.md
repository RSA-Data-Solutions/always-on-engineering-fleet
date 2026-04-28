# Claude Code Routines — Routines 2, 3 & 4 (Team Plan)

Definitive specs for the three non-smoke routines. These supersede the
prompt stubs in `routines-1-2-3.md` and the Routine 4 section of
`routines-final.md` for the **Team plan** setup (25 runs/day cap).

The GitHub Action for Routine 4 now uses the `inputs` JSON format with
`x-api-key` authentication — update both repos' `release-qa.yml`.

---

## Routine 2 — Daily signup + first-run UX

**Name:** `qa-signup-daily`  
**Schedule:** `0 2 * * *` local time (UTC offset handled in routine settings)  
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
**Trigger:** `/fire` endpoint, called from GitHub Action on push to `main`
in either `RSA-Data-Solutions/inova` or `RSA-Data-Solutions/IBMiMCP`

### GitHub Action

Add to **both** repos as `.github/workflows/release-qa.yml` (already
present — update to the `inputs` format below):

```yaml
name: Fire QA regression routine

# Setup (one time, in BOTH repos):
#   1. Copy your Anthropic API key for the QA workspace
#   2. In GitHub: Settings → Secrets and variables → Actions → New secret
#        ANTHROPIC_API_KEY_QA  → your Anthropic API key

on:
  push:
    branches: [main]

jobs:
  fire-qa:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger QA regression routine
        env:
          ANTHROPIC_API_KEY_QA: ${{ secrets.ANTHROPIC_API_KEY_QA }}
          COMMIT_SHA: ${{ github.sha }}
          COMMIT_TIMESTAMP: ${{ github.event.head_commit.timestamp }}
          AUTHOR: ${{ github.event.head_commit.author.name }}
          SOURCE_REPO: ${{ github.repository }}
        run: |
          set -euo pipefail
          if [[ -z "${ANTHROPIC_API_KEY_QA:-}" ]]; then
            echo "ANTHROPIC_API_KEY_QA secret not set — skipping QA fire."
            echo "Add it under repo Settings → Secrets and variables → Actions."
            exit 0
          fi

          payload=$(jq -n \
            --arg source_repo "$SOURCE_REPO" \
            --arg commit_sha "$COMMIT_SHA" \
            --arg commit_timestamp "$COMMIT_TIMESTAMP" \
            --arg author "$AUTHOR" \
            '{inputs: {
              source_repo: $source_repo,
              commit_sha: $commit_sha,
              commit_timestamp: $commit_timestamp,
              author: $author
            }}')

          response=$(curl -sS -w "\n%{http_code}" -X POST \
            "https://api.anthropic.com/v1/code/routines/qa-release-regression/fire" \
            -H "x-api-key: $ANTHROPIC_API_KEY_QA" \
            -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
            -H "Content-Type: application/json" \
            -d "$payload")

          body=$(echo "$response" | sed '$d')
          status=$(echo "$response" | tail -n1)

          echo "HTTP $status"
          echo "$body"

          if [[ "$status" -ge 400 ]]; then
            echo "::error::Failed to fire QA regression routine (HTTP $status)"
            exit 1
          fi

          session_url=$(echo "$body" | jq -r '.claude_code_session_url // empty')
          if [[ -n "$session_url" ]]; then
            echo "::notice::QA routine session: $session_url"
          else
            echo "::notice::QA routine fired for ${COMMIT_SHA}"
          fi
```

### Routine prompt

```
Launch Ram with:

  skill_path:         SKILL.md
  context_file:       contexts/inova.md
  max_iterations:     8
  enable_research:    false
  human_instructions: |
    Post-deploy regression for {{ inputs.commit_sha }} from
    {{ inputs.source_repo }} (authored by {{ inputs.author }} at
    {{ inputs.commit_timestamp }}).

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
```

---

## Cap accounting (Team plan, 25 routine runs/day)

| Routine | Runs/day | Cap used |
|---|---|---|
| 1. Smoke (90min) | 11 (07:00–23:00) | 44% |
| 2. Signup daily | 1 | 4% |
| 3. Explore daily | 1 | 4% |
| 4. Post-deploy | variable (webhook) | metered overage |

Scheduled total: **52% of Team cap.** Enable metered overage in
Settings → Billing before heavy deploy days. Pro plan (5/day) and Max
plan (15/day) cannot accommodate this schedule; Team is the floor.

---

## Watchdog (external, runs on homelab)

See `scripts/watchdog/qa-heartbeat-check.sh` for the implementation.

### cron entry (Linux homelab)

```bash
# /etc/cron.d/qa-fleet-watchdog — runs every 15 min
*/15 * * * * sashi FLEET_DIR=/path/to/always-on-engineering-fleet ALERT_EMAIL=you@example.com /usr/local/bin/qa-heartbeat-check.sh
```

Set `FLEET_DIR` to wherever the repo is cloned on the homelab. The
script reads heartbeat files from `$FLEET_DIR/fleet-workspace/heartbeats/`.

Missing heartbeat = the QA fleet is silently broken. Treat as
`severity/P1` — you're flying blind until it's fixed, even if no bugs
are in the queue.
