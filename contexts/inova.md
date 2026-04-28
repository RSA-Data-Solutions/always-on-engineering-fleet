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

- Hacker News — agentic IDE pain, AI coding assistant friction
- r/LocalLLaMA — self-hosted AI tooling gaps, MCP issues
- r/ClaudeAI, r/ChatGPT — power user friction with AI coding tools
- GitHub Issues on similar projects (Continue, Cursor, open-source AI IDEs)
- Discord: Cursor, Continue, Zed servers

**Research focus:** Gaps in iNova's agentic workflow. High priority: context management,
multi-agent coordination, IBM i integration, developer UX friction, deployment automation.

---

## P0 Tool Suite

Tools tested in **every smoke run** (Routine 1). Excluded from `rotation_batches` below
so they are not double-counted in the daily rotation. Add a tool here when it is
certified as business-critical and must never regress overnight.

```yaml
P0_tool_suite:
  - listTables
  - runSQL
  # Add further P0 tools here as they are certified
```

---

## Rotation testing (for Routine 3)

### `ui_journey_rotation_command`

Run against **Aaron's locally deployed IBMiMCP staging server** (`http://localhost:3051`),
not the live `inovaide.com` site. Aaron must certify the server (STEP 3 of Routine 3)
before this command is invoked.

```bash
cd {iNova}/qa
source .venv/bin/activate
QA_HEADLESS=true \
QA_BASE_URL=http://localhost:3051 \
QA_TENANT_EXPLORE_PASSWORD=$QA_TENANT_EXPLORE_PASSWORD \
  python -m pytest ui_journey/test_rotation.py -v \
  --rotation-day=$(date +%A) \
  --json-report --json-report-file=/tmp/rotation-report.json
```

### `rotation_batches`

Populated by the **Sunday weekly refresh** (STEP 7 of Routine 3). Each entry lists
IBMiMCP tool names to test on that day. Tools in `P0_tool_suite` above are excluded
— they are covered by Routine 1 smoke tests instead.

On a fresh install all batches are empty. The first Sunday refresh fills them in.
Do not edit this section manually — let STEP 7 manage it.

```yaml
rotation_batches:
  Monday:    []
  Tuesday:   []
  Wednesday: []
  Thursday:  []
  Friday:    []
  Saturday:  []
  Sunday:    []
```
