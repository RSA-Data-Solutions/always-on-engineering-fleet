# Project Context — iNova

This context file tells the engineering fleet about the iNova project.

---

## Project identity

| Field | Value |
|-------|-------|
| Name | iNova |
| Description | Agentic IDE platform — containerised AI coding environment with orchestration |
| Repo path | `/Users/Sashi/Documents/projects/iNova` |
| Languages | Python (orchestrator), TypeScript / Next.js (frontend) |
| Test runner | Python pytest (orchestrator) + smoke tests |

---

## Architecture overview

```
iNova/
├── orchestrator/         Python / FastAPI backend
│   ├── app/              routes, services, models
│   ├── alembic/          DB migrations
│   └── tests/            pytest suite
├── frontend/             Next.js (TypeScript, Tailwind)
│   ├── app/              App Router pages
│   └── components/
├── code-server-base/     Docker image for the AI coding environment
├── scripts/              deploy, migrate, backup, smoke tests
└── docker-compose*.yml   Multiple deployment profiles
```

---

## Commands

```yaml
install_command:     "cd orchestrator && pip install -r requirements.txt"
test_command:        "cd orchestrator && python -m pytest tests/ -v"
smoke_test_command:  "python3 scripts/smoke_tests.py"
build_command:       "docker compose -f docker-compose.dev.yml build"
start_command:       "docker compose -f docker-compose.dev.yml up -d"
```

> Run `scripts/migrate.sh` after any schema change to apply Alembic migrations.

---

## QA journey commands

Used by Routines 2, 3, and 4. All commands assume the working directory is
`{iNova}/qa` with a virtualenv active.

**Setup (once per session):**
```bash
cd {iNova}/qa
python3 -m venv .venv && source .venv/bin/activate
pip install -q -r requirements.txt
playwright install --with-deps chromium
```

**ui_journey_signup_command** — Routine 2, tests PROD `https://inovaide.com`:
```bash
QA_HEADLESS=true \
QA_BASE_URL=https://inovaide.com \
QA_BYPASS_SECRET=$QA_BYPASS_SECRET \
  python -m pytest ui_journey/test_signup.py -v \
  --json-report --json-report-file=/tmp/signup-report.json
```

**ui_journey_rotation_command** — Routine 3, tests Aaron-certified staging:
```bash
QA_HEADLESS=true \
QA_BASE_URL=$QA_BASE_URL \
QA_TENANT_EXPLORE_EMAIL=$QA_TENANT_EXPLORE_EMAIL \
QA_TENANT_EXPLORE_PASSWORD=$QA_TENANT_EXPLORE_PASSWORD \
  python -m pytest ui_journey/test_rotation.py -v \
  --rotation-day=$(date +%A) \
  --json-report --json-report-file=/tmp/rotation-report.json
```

**ui_journey_test_command** — Routine 4 full suite (P0 + all 7 rotation batches):
```bash
# P0 suite
QA_HEADLESS=true \
QA_BASE_URL=$QA_BASE_URL \
QA_TENANT_SMOKE_PASSWORD=$QA_TENANT_SMOKE_PASSWORD \
  python -m pytest ui_journey/test_p0_suite.py -v \
  --json-report --json-report-file=/tmp/p0-report.json

# All 7 rotation batches
for day in Monday Tuesday Wednesday Thursday Friday Saturday Sunday; do
  QA_HEADLESS=true \
  QA_BASE_URL=$QA_BASE_URL \
  QA_TENANT_EXPLORE_EMAIL=$QA_TENANT_EXPLORE_EMAIL \
  QA_TENANT_EXPLORE_PASSWORD=$QA_TENANT_EXPLORE_PASSWORD \
    python -m pytest ui_journey/test_rotation.py -v \
    --rotation-day=$day \
    --json-report --json-report-file=/tmp/rotation-${day}-report.json
done
```

---

## QA tenants

```yaml
qa_tenants:
  signup_bot:
    email_template: "qa+{unix_timestamp}@inovaide-qa.com"
    gc_routine:     "weekly-gc-signup-bot"
    note: >
      Each Routine 2 run generates a fresh address using the unix timestamp
      at invocation time. Never reuse. The weekly GC routine prunes accounts
      older than 7 days.

  smoke:
    email:        "qa-smoke@inovaide-qa.com"
    password_env: "QA_TENANT_SMOKE_PASSWORD"

  explore:
    email_env:    "QA_TENANT_EXPLORE_EMAIL"
    password_env: "QA_TENANT_EXPLORE_PASSWORD"
```

---

## Rotation batches

Used by `test_rotation.py` via `--rotation-day` and referenced in Routine 3.
Each batch covers non-P0 tools in the IBMiMCP tool tree. Batches are populated
from the live `tools/list` response on first run; the table below shows the
intended grouping.

| Day | Tool category |
|-----|---------------|
| Monday | `src/tools/system/*` (non-P0) |
| Tuesday | `src/tools/job/*` (non-P0) |
| Wednesday | `src/tools/sql/*` (non-P0) |
| Thursday | `src/tools/source/*` (non-P0) |
| Friday | `src/tools/library/*` + `src/tools/ifs/*` (non-P0) |
| Saturday | `src/tools/security/*` (non-P0) |
| Sunday | catch-all — newly added tools |

---

## Environment

Copy `.env.dev.example` to `.env` and fill in values before testing. Key vars:

```bash
# Database
DATABASE_URL=postgresql://...

# Auth
JWT_PRIVATE_KEY_PATH=keys/jwt_private.pem
JWT_PUBLIC_KEY_PATH=keys/jwt_public.pem

# IBM i MCP (if testing IBM i integration)
IBMIMCP_URL=http://localhost:3051
IBMIMCP_API_KEY=...

# QA-specific
QA_BYPASS_SECRET=...           # enables QA bypass for email verification (Routine 2)
QA_TENANT_SMOKE_PASSWORD=...   # password for the long-lived smoke tenant
QA_TENANT_EXPLORE_EMAIL=...    # long-lived exploration tenant (Routine 3 / 4)
QA_TENANT_EXPLORE_PASSWORD=...
```

The `.env` file is gitignored. Never commit secrets.

---

## Git remote

```yaml
push_remote:  origin
push_branch:  main
github_repo:  https://github.com/RSA-Data-Solutions/iNova
```

---

## Test suite

The orchestrator pytest suite in `orchestrator/tests/` covers:
- API route integration tests
- Service unit tests
- Rate limiting tests (`test_rate_limiting.py`)

Smoke tests in `scripts/smoke_tests.py` cover end-to-end HTTP flows.

A test passes when: pytest exit code 0, no uncaught exceptions in smoke tests.

---

## Known quirks and constraints

- Docker services must be running for integration tests; start with `docker compose up -d`
- JWT keys must exist in `keys/` before starting the orchestrator
- DB migrations must be applied before running tests
- The `code-server-base` Docker image takes ~5 min to build; don't rebuild unless needed
- CI/CD workflows in `.github/workflows/` are the source of truth for deployment
- Twingate is used for remote access — see `.github/TWINGATE_SETUP.md`

---

## Human scope (default)

Unless overridden at fleet launch:
- Fix any test failure in `orchestrator/tests/`
- Do not modify deployment scripts unless the test directly tests deployment
- Do not touch `.env` files or `keys/`
- Do not modify docker-compose files unless necessary to fix a test
- Do not add new features unless a Dhira proposal is approved

---

## Research communities (for Dhira)

**Routine 3 / Phase A — IBM i focus (search daily, last 24 h):**
- code400.com — IBM i developer Q&A and operational complaints
- r/IBMi — IBM i community discussions
- IBM i OSS Slack — open-source tooling pain points
- #IBMiOSS on X — public IBM i OSS conversations
- Issue trackers for RSA-Data-Solutions/inova and RSA-Data-Solutions/IBMiMCP

**General iNova research:**
- Hacker News — agentic IDE pain, AI coding assistant friction
- r/LocalLLaMA — self-hosted AI tooling gaps, MCP issues
- r/ClaudeAI, r/ChatGPT — power user friction with AI coding tools
- GitHub Issues on similar projects (Continue, Cursor, open-source AI IDEs)
- Discord: Cursor, Continue, Zed servers

**Research focus:** Gaps in iNova's agentic workflow. High priority: context management,
multi-agent coordination, IBM i integration, developer UX friction, deployment automation.
