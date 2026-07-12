# Routine 1 — Daily Signup Regression (`qa-signup-daily`)

Hermes-native cron job. Runs against the LIVE inovaide.com — every run creates a brand-new user.

## Schedule

```
Cron:     0 8 * * *
Timezone: UTC
```

This is **02:00 Central Time daily** (low traffic, good time for fresh account
creation that won't compete with real users on the live site).

## Hermes cron job config

```yaml
schedule: "0 8 * * *"
name: "QA Signup Daily"
deliver: "slack"
workdir: /Users/Sashi/Documents/projects/iNova
enabled_toolsets: ["web", "terminal", "file"]
```

## Prompt

```
You are the orchestrator for a daily fresh-signup regression. This runs
against the LIVE inovaide.com — every run creates a brand-new user.

FLEET_PATH=/Users/Sashi/Documents/projects/always-on-engineering-fleet
INOVA_PATH=/Users/Sashi/Documents/projects/iNova

You play Ram and Lynn in this session — no Aaron (we are not deploying),
no Sam (do not push fixes from a daily run).

STEP 1 — Read your manual.
Read:
    {FLEET_PATH}/SKILL.md
    {FLEET_PATH}/agents/ram.md
    {FLEET_PATH}/agents/lynn.md
    {FLEET_PATH}/contexts/inova.md

STEP 2 — Act as Lynn (QA).
Per lynn.md, run the signup journey:
    cd {INOVA_PATH}/qa
    source ../.venv/bin/activate
    python -m venv .venv && source .venv/bin/activate
    pip install -q -r requirements.txt
    playwright install --with-deps chromium --force
    QA_HEADLESS=true \
    QA_BASE_URL=$(grep QA_BASE_URL {INOVA_PATH}/.env | cut -d= -f2) \
    QA_BYPASS_SECRET=$(grep QA_BYPASS_SECRET {INOVA_PATH}/.env | cut -d= -f2) \
    QA_TENANT_SMOKE_PASSWORD=$(grep QA_TENANT_SMOKE_PASSWORD {INOVA_PATH}/.env | cut -d= -f2) \
      python -m pytest ui_journey/test_signup.py -v \
      --json-report --json-report-file=/tmp/signup-report.json

The test:
    - Pre-flight: verifies QA_BYPASS_SECRET matches the server's secret
      (added in PR #39). If mismatch detected, fails fast with diagnostic.
    - Generates a fresh email qa+{unix_timestamp}@inovaide-qa.com
    - Sends signup with X-QA-Bypass HMAC header (skips email verify)
    - Logs in, opens VS Code, waits for OpenCode CLI ready
    - Invokes listTables as the first canonical tool call
    - Asserts each step completes within thresholds in
      qa/baseline_metrics.json (signup_journey key) or DEFAULT_THRESHOLDS

STEP 3 — Triage and file.
For each failure in /tmp/signup-report.json:
    - Route ALL failures to RSA-Data-Solutions/iNova (signup is
      platform_failure by definition — even a tool call failure here
      means the journey didn't complete, which is platform-side)
    - Severity:
        - Step fails outright (signup, login, IDE boot, OpenCode init,
          first tool call) → severity/P0
        - Step exceeds threshold but completes → severity/P1
        - Email delivery >180s (if bypass disabled and real email used)
          → severity/P1
    - Apply dedup hash logic (same as Routine 1).
    - Add labels: qa-bot, platform-bug, auto-filed, severity/Px.
    - File issues using gh CLI:
      gh issue create --repo RSA-Data-Solutions/iNova \
        --title "[qa-bot] {title}" \
        --body "{body}" \
        --label "qa-bot,platform-bug,auto-filed,severity/{P0|P1}"

STEP 4 — Do NOT delete the created account.
Leave it in the database. A separate weekly GC routine prunes old
signup_bot accounts. Do NOT reuse the email — every run uses a fresh one.

STEP 5 — Heartbeat.
Append UTC timestamp to:
    {FLEET_PATH}/fleet-workspace/heartbeats/qa-signup-daily.txt
Commit and push:
    cd {FLEET_PATH}
    git add fleet-workspace/heartbeats/qa-signup-daily.txt
    git commit -m "heartbeat: qa-signup-daily {timestamp}"
    git push origin main

STEP 6 — Notifications.
- Send summary to Slack channel #hermes-automation with:
    - Number of tests run, passed, failed
    - Number of P0s, P1s
    - Link to any GitHub issues filed
    - Link to the report in /tmp/signup-report.json
- If any human action is needed (P0 failure, secret mismatch, etc.):
  Send SMS to 6304156484@tmomail.net via:
    echo "{summary}" | mail -s "iNova QA Alert" 6304156484@tmomail.net
- Write a summary on Notion. If no page exists, create a new page and
  add the summary under a "QA Daily Reports" section. Use the notion skill
  or ntn CLI to create/update the page.

Hard limits:
- Run time cap: 10 minutes.
- Never log the QA_BYPASS_SECRET, the bypass token, or the test password.
- Never delete QA accounts created during the run.
```

## What changed from Claude routine

| Claude Routine | Hermes Cron |
|---|---|
| Step 0: `ls -la ~ /workspace` to discover paths | **Removed** — paths hardcoded above |
| GitHub connector API for issue filing | **gh CLI** via terminal tool |
| No notifications | **Slack + SMS + Notion** built-in |
| Ephemeral sandbox venv setup | **Local Mac** — .venv persists, faster setup |
| Routine env panel for secrets | **Read from .env file** on disk |