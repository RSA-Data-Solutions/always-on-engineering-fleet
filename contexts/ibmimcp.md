# Project Context — IBMiMCP

This context file tells the engineering fleet about the IBMiMCP project.

---

## Project identity

| Field | Value |
|-------|-------|
| Name | IBMiMCP |
| Description | MCP server with 130+ tools for IBM i (AS/400) access via SSH/JDBC |
| Repo path | `/Users/Sashi/Documents/projects/IBMiMCP` |
| Language | TypeScript / Node.js |
| Test runner | Python (`python3 run_tests.py`) |

---

## Commands

```yaml
install_command: "npm install --include=dev && npm run build"
test_command:    "python3 run_tests.py"
build_command:   "npm run build"
start_server:    "node dist/server.js"
```

> **Node version note:** Always use `npm install --include=dev` — without it, TypeScript
> and other devDependencies are silently skipped on Node v25+.

---

## Environment

```bash
PORT=3051
ADMIN_API_KEY=3a309d556b6b6cd874a1f964b9b336e946e10aa0bc70651d
```

Start the server before running tests:
```bash
cd /Users/Sashi/Documents/projects/IBMiMCP
PORT=3051 ADMIN_API_KEY=3a309d556b6b6cd874a1f964b9b336e946e10aa0bc70651d \
  node dist/server.js &
sleep 3
```

IBM i credentials are embedded in `run_tests.py` — no additional env vars needed.

---

## Git remote

```yaml
push_remote:  origin
push_branch:  main
github_repo:  https://github.com/RSA-Data-Solutions/IBMiMCP
```

---

## IBM i target system

| Setting | Value |
|---------|-------|
| Host | `pub400.com` |
| SSH Port | `2222` |
| User | `MSASHI` |
| Password | `JUMANJI1` |
| OS Version | V7R5M0 |
| CCSID | 273 (German EBCDIC) |
| Default library | `MSASHI1` |

---

## Test suite (19 tests)

| Category | Tools tested |
|----------|-------------|
| System | getSystemStatus, getDiskUsage, getPerformanceMetrics, listSubsystems, getSystemHistory |
| Jobs | listActiveJobs (×2), getJobLog (×2) |
| SQL | runSQL, listTables, describeTable |
| Source | listSourceMembers, getSourceMember |
| Library/Object | listObjects (×2) |
| IFS | listIFSDirectory, readIFSFile |
| Security | getUserProfile |

A test passes when: no MCP protocol error AND `"success": true` in response JSON.

---

## Source structure

```
src/
├── tools/
│   ├── system/     getDiskUsage, getSystemStatus, getSystemHistory, ...
│   ├── job/        listActiveJobs, getJobLog, submitJob, ...
│   ├── sql/        runSQL, runSQLScript, listTables, describeTable, ...
│   ├── source/     getSourceMember, listSourceMembers, updateSourceMember, ...
│   ├── library/    listObjects, ...
│   ├── ifs/        listIFSDirectory, readIFSFile, writeIFSFile
│   └── security/   getUserProfile, listUserProfiles, grantAuthority, ...
├── server.ts
└── utils/
```

Each tool is a TypeScript file exporting a `ToolDefinition` with `name`, `description`,
`inputSchema` (zod), and `handler` (calls `context.ibmiClient.runSql()` or `runCommand()`).

---

## Known bugs fixed (as of 2026-04-01)

All 19 tests pass. If tests start failing again, look for these patterns:

| Tool | Pattern |
|------|---------|
| SQL tools | Wrong column names — always verify against QSYS2.SYSCOLUMNS |
| getSystemHistory | Use `TABLE(QSYS2.HISTORY_LOG_INFO(START_TIME=>...))`, not SYSTEM_LOG |
| listActiveJobs | Use short status codes: RUN/EVTW/MSGW — not full words |
| getUserProfile | Column names end in `_NAME` |
| getJobLog | Use `TABLE(QSYS2.JOBLOG_INFO('*'))` — DSPJOBLOG blocked on pub400 |

---

## Known quirks and constraints

- `db2` CLI: permission denied for MSASHI — use JDBC via MCP server only
- `STRSQL`: disallowed for public users on pub400
- FTP port 8021 blocked — iSync FTP fails; use SSH-based sync
- PASE Python3: `/QOpenSys/pkgs/bin/python3`
- Do not modify `run_tests.py` credentials

---

## Human scope (default)

Unless overridden at fleet launch:
- Fix any tool that causes a test failure
- Do not refactor working tools
- Do not add new tools unless Dhira proposal is approved
- Do not modify `run_tests.py` or documentation (except to correct renamed parameters)

---

## Research communities (for Dhira)

- Code400 (code400.com) — RPGLE, SQL, API, tooling threads
- r/IBMi on Reddit — VS Code, debugging, modernisation
- IBM Community IBM i groups — admin and modernisation pain
- IBM i OSS Slack / Ryver — real-time developer friction
- #IBMiOSS on X/Twitter
- LinkedIn IBM i / AS400 groups

**Research focus:** Gaps in IBMiMCP's 130+ tools. High priority: debugging, observability,
modernisation bridges, automation of manual admin tasks.
