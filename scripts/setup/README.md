# Phase 1-2-3 setup script

One script that walks through:

- Phase 1 — generate QA bypass secret, add to .env, verify bypass works
- Phase 2 — create GitHub labels, commit + push to all three repos
- Phase 3 — add /health and /api/mcp/status endpoints, restart, test

## Where to run it

**Run from your Mac.** Even if your orchestrator runs on the homelab,
this script edits files on your Mac (where the repos live) and then
calls `docker compose restart` and `curl` against whatever URL points
at the orchestrator.

If your orchestrator is:

- **Local Docker on your Mac:** TARGET_URL=http://localhost:8000 (default)
- **Homelab via Twingate/Tailscale:** TARGET_URL=http://homelab.local:8000
  or whatever resolves
- **Production via Cloudflare:** TARGET_URL=https://inovaide.com
  (but then you can't `docker compose restart` — script will skip that
  step and you restart manually on the host)

Set TARGET_URL once before running:

```bash
export TARGET_URL=http://homelab.local:8000
./phase-1-2-3.sh
```

## What it does interactively

The script prompts at every destructive step:

- Before generating secrets → confirms before overwriting
- Before docker restart → asks (so you can pick the right compose file)
- Before each `git commit` → shows the staged diff stat
- Before each `git push` → final confirmation
- After endpoint tests → shows responses, asks if you want to continue

Defaults are conservative — answering "no" or pressing Enter skips.
Answering "y" proceeds.

## Dry run

```bash
./phase-1-2-3.sh --dry-run
```

Shows every command it would execute, makes zero changes. Useful for
reading through it before committing.

## Resuming from a partial run

```bash
./phase-1-2-3.sh --skip-phase-1               # Phase 1 done, do 2 and 3
./phase-1-2-3.sh --skip-phase-1 --skip-phase-2 # only Phase 3
```

Phases are idempotent within reason — re-running Phase 1 detects an
existing QA_BYPASS_SECRET and reuses it. Re-running Phase 2 will hit
"nothing to commit" and warn but won't error.

## What it does NOT do (manual steps)

1. **SQL UPDATE for QA tenants** — needs your DB password, easier
   interactively. The script tells you the exact SQL to run.

2. **Edit main.py** — too brittle to automate. The script tells you
   the two lines to add and waits for you to confirm.

3. **Sign up qa-smoke and qa-explore via the UI** — interactive UI
   work, can't automate. Do it before the SQL UPDATE.

4. **Phase 4-7** — the homelab cron install, routine creation in
   claude.ai/code/routines, workflow activation, watchdog install
   are all separate steps for tomorrow.

## What if it fails partway through?

Each phase is a self-contained block with `set -euo pipefail`. If
Phase 1 fails, Phases 2-3 don't run. You can fix the issue and re-run:

```bash
./phase-1-2-3.sh --skip-phase-1   # if Phase 1 already partially worked
```

Common failures and fixes:

- **`gh: not authenticated`** → run `gh auth login`
- **`docker compose ... not found`** → check `COMPOSE_FILE` env var
- **`bypass test got 'check your email'`** → orchestrator didn't pick
  up the env var. Re-run `docker compose restart orchestrator` and
  re-run the test by hand:
  ```bash
  source <(grep QA_BYPASS_SECRET /path/to/iNova/.env)
  EMAIL="qa+$(date +%s)@inovaide-qa.com"
  TOKEN=$(echo -n "$EMAIL" | openssl dgst -sha256 -hmac "$QA_BYPASS_SECRET" | awk '{print $2}')
  curl -X POST $TARGET_URL/auth/signup -H "Content-Type: application/json" \
    -H "X-QA-Bypass: $TOKEN" \
    -d "{\"email\":\"$EMAIL\",\"name\":\"X\",\"password\":\"TestPass123!\"}"
  ```
- **endpoints return 404** → main.py edit didn't land or the import
  path is wrong. Check `docker compose logs orchestrator` for
  ImportError.

## Safety properties

- Will NOT push without explicit y/n confirmation each commit
- Will NOT commit anything containing `.env`, `.venv/`, or `qa-artifacts/`
- Scans for accidental hex-string secrets in source files before
  staging
- Generates QA bypass secret with `openssl rand -hex 32` (cryptographic
  PRNG)
- Never echoes the secret value to log output beyond first generation
