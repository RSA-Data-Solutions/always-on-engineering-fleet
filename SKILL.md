---
name: engineering-fleet
description: >
  Deploy an Always-On Software Engineering Fleet — four AI agents (Ram, Lynn, Sam,
  and Dhira the Research Agent) that autonomously discover, build,
  test, fix, and ship software in a continuous loop. Use this skill whenever the user
  wants to automate software quality improvement, run a fix-test-push cycle, discover
  new tool ideas from community pain points, set up autonomous agents to work on bugs
  or failing tests, or says things like "fix all bugs", "run the fleet", "start the
  engineering agents", "find new tool ideas", "autonomous testing loop", "run Dhira",
  or "let the agents handle it". Point the fleet at any project by selecting a context
  file from contexts/. Available projects: IBMiMCP, iNova, self-improvement.
---

# Always-On Software Engineering Fleet

Five specialised agents work together to discover, build, test, deploy, and ship software
across multiple projects. Two loops run in parallel: a **fix loop** (QA → SE → DevOps → QA → push) and
a **discovery loop** (Dhira → Ram review → SE build → DevOps deploy → QA test → release).

```
Dhira (Research Agent) ── daily ──→ proposals/ ──→ CTO review
                                                         │
Ram (orchestrator)                              approve / reject
 ├─ fix loop:   QA → analyze → SE(s) → DevOps → QA → push    │
 └─ build loop: approved proposal → SE builds → DevOps → QA → release
```

The fleet is **project-agnostic** — swap the context file to target a different project.

---

## Agents

- **Ram** — Orchestrator. Reads context, manages both loops, reviews Dhira's proposals,
  analyzes bug dependencies, decides parallelism, controls git (push, rollback, release),
  pauses for budget.
- **Aaron** — Deployment owner. Kills stale server processes, builds from source,
  starts the server, runs health checks and endpoint smoke tests, verifies registered tool
  count, and communicates a READY/FAILED status to the fleet before QA runs. QA always
  tests against a server Aaron (DevOps) has certified.
- **Lynn** — Tester. Runs the project's test suite, captures structured results,
  classifies failures, tests newly built tools before release. When `server_already_running`
  is true, skips server setup and tests against the DevOps-certified instance.
- **Sam** — Builder & Fixer. Receives bug assignments or new tool builds,
  reads relevant code, makes targeted changes, verifies locally, reports back to Ram.
- **Dhira** — Research Agent. Searches developer communities for pain points, identifies
  gaps in the target project's toolset, writes structured proposals for Ram to review.

---

## How to start the fleet

1. **Choose a project context file** from `contexts/`. Each file describes one project's
   repo path, test command, environment setup, and any known quirks:
   - `contexts/ibmimcp.md` — IBMiMCP MCP server (IBM i tools, pub400.com, QSYS2 SQL)
   - `contexts/inova.md` — iNova agentic IDE platform (Docker / Python / Next.js)
   - `contexts/self-improvement.md` — The fleet improves its own agent instructions

2. **Read `agents/ram.md`** — it is Ram's full operating manual. Launch Ram as a
   subagent, passing:
   - the path to this `SKILL.md`
   - the path to the project context file
   - the iteration cap (default: 10)
   - any human instructions (e.g. "focus on SQL tools only", "don't touch authentication")

3. **Ram runs the loop.** It communicates progress by writing artefact files to
   `fleet-workspace/iteration-N/`. Watch progress there.

4. **When the fleet pauses** (budget low, unresolvable failure, or all tests passing),
   Ram writes a summary to `fleet-workspace/summary.md` and notifies you.

---

## Agent instruction files

- `agents/ram.md` — Full CTO operating manual
- `agents/aaron.md` — DevOps Engineer instructions (deploy, health check, smoke test)
- `agents/lynn.md` — QA Engineer instructions
- `agents/sam.md` — Software Engineer instructions
- `agents/dhira.md` — Research Agent instructions

---

## Project context files

Each project context file tells the fleet about one specific project:

| Field | Purpose |
|-------|---------|
| `repo_path` | Absolute path to the git repository |
| `test_command` | Command to run the full test suite |
| `install_command` | Command to install dependencies (run once) |
| `environment` | Key env vars or setup steps |
| `push_remote` | Git remote and branch to push to |
| `known_quirks` | Common gotchas, flaky tests, out-of-scope areas |
| `human_scope` | Human-imposed constraints for this run |
| `research_communities` | Where Dhira should search for pain points |

---

## Workspace layout

```
fleet-workspace/
├── summary.md                        ← live status; final state on exit
├── proposals/
│   ├── index.md                      ← proposal tracker (pending/approved/rejected/built)
│   ├── dhira-summary-YYYY-MM-DD.md   ← daily research summary
│   └── YYYY-MM-DD-<change>.md        ← one file per proposed tool/change
└── iteration-N/
    ├── qa-report.json
    ├── dependency-graph.json
    ├── assignments/
    │   └── bug-<id>.json
    ├── fixes/
    │   └── bug-<id>-report.json
    └── retest-report.json
```

---

## Dependency-aware parallelism

Ram analyses failing tests before spawning SEs:

1. Build a dependency graph: does fixing bug A require first fixing bug B?
2. Independent bugs → spawn parallel SE subagents (one per bug or cluster)
3. Dependent bugs → group into a sequential chain

---

## Budget awareness

Before each iteration Ram checks remaining capacity. If insufficient for another full
loop, it writes a pause summary and waits for human authorisation to continue.

---

## Quick-start examples

**Fix loop (bugs only):**
```
Ram context_file: contexts/ibmimcp.md
max_iterations: 5
human_instructions: "Fix failing tools. Do not touch compile tools."
```

**Research run (Dhira only):**
```
Dhira agent_file: agents/dhira.md
context_file: contexts/ibmimcp.md
human_instructions: "Search today's IBM i communities. Focus on debugging pain."
```

**Full fleet — iNova:**
```
Ram context_file: contexts/inova.md
max_iterations: 10
enable_research: true
human_instructions: "Fix all failing tests. Run Dhira for new feature ideas."
```

**Self-improvement run:**
```
Ram context_file: contexts/self-improvement.md
max_iterations: 3
human_instructions: "Review past iteration summaries. Improve agent clarity and coverage."
```
