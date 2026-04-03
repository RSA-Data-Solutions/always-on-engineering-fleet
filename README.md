# Always-On Engineering Fleet

An autonomous AI engineering team that continuously discovers, builds, tests, fixes, and ships
software across multiple projects. Four specialised agents work in two parallel loops — a
**fix loop** and a **discovery loop** — and can be pointed at any project by swapping a
context file.

## Projects

| Project | Context file | Description |
|---------|-------------|-------------|
| IBMiMCP | `contexts/ibmimcp.md` | MCP server with 130+ IBM i tools |
| iNova | `contexts/inova.md` | Agentic IDE platform (Docker / Python / Next.js) |
| Self-improvement | `contexts/self-improvement.md` | Fleet improves its own agent instructions |

## How to launch

### Fix loop (bugs only)
```
Launch the CTO agent with:
  skill_path:         /Users/Sashi/Documents/projects/always-on-engineering-fleet/SKILL.md
  context_file:       /Users/Sashi/Documents/projects/always-on-engineering-fleet/contexts/ibmimcp.md
  max_iterations:     5
  human_instructions: "Fix all failing tests. Do not touch compile tools."
```

### Research run (Dhira only)
```
Launch Dhira with:
  agent_file:         agents/dhira.md
  context_file:       contexts/ibmimcp.md
  human_instructions: "Search today's IBM i communities. Focus on debugging pain."
```

### Full fleet (fix + discover + self-improve)
```
Launch the CTO agent with:
  skill_path:         /Users/Sashi/Documents/projects/always-on-engineering-fleet/SKILL.md
  context_file:       contexts/ibmimcp.md
  max_iterations:     10
  enable_research:    true
  human_instructions: "Run Dhira daily. Fix all failing tests. Review proposals before building."
```

## Agents

| Agent | File | Role |
|-------|------|------|
| CTO | `agents/cto.md` | Orchestrator — runs both loops, owns git push authority |
| QA Engineer | `agents/qa-engineer.md` | Runs test suite, produces structured failure reports |
| Software Engineer | `agents/software-engineer.md` | Fixes bugs or builds new tools |
| Dhira | `agents/dhira.md` | Researches developer communities for pain points and proposals |

## Workspace

The fleet writes all runtime artefacts to `fleet-workspace/`:

```
fleet-workspace/
├── summary.md                  ← live status; final state on exit
├── proposals/
│   ├── index.md                ← proposal tracker
│   ├── dhira-summary-*.md      ← daily research summaries
│   └── YYYY-MM-DD-<tool>.md   ← one file per proposed tool/change
└── iteration-N/
    ├── qa-report.json
    ├── dependency-graph.json
    ├── assignments/
    ├── fixes/
    └── retest-report.json
```

`fleet-workspace/iteration-*/` is gitignored (runtime only). `proposals/index.md` is committed.

## Self-improvement

The fleet can target its own repo (`contexts/self-improvement.md`). In this mode:
- Dhira reviews past iteration summaries and community feedback on AI agent design
- The CTO approves changes to agent instruction files (`agents/*.md`)
- The SE edits agent files; QA validates consistency (no broken references, format checks)
- Changes are committed and pushed like any other project

## Adding a new project

1. Copy `contexts/ibmimcp.md` to `contexts/<project-name>.md`
2. Fill in `repo_path`, `test_command`, `install_command`, `environment`, and `known_quirks`
3. Launch the fleet pointing at the new context file
