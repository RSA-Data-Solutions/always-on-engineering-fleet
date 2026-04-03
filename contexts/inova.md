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
