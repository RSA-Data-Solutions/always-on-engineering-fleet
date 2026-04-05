# Always-On Engineering Fleet — Claude Instructions

## What this repo is

This is a standalone agentic engineering team. It contains agent instruction files,
project context files, and a runtime workspace. It is NOT a software project itself —
it is the team that works ON software projects.

## How to use this repo

To launch the fleet against a project:

1. Read `SKILL.md` — it is the master operating manual.
2. Read the relevant context file in `contexts/` — it tells you everything about the
   target project (repo path, test command, credentials, known quirks).
3. Launch the CTO subagent using `agents/ram.md`.

## Key rules

- **Never modify agent files without going through the self-improvement loop** (contexts/self-improvement.md).
  Ad-hoc edits to agent files are how the fleet drifts.
- **fleet-workspace/ is runtime state** — do not read it as ground truth about project health.
  Always re-run QA to get the current state.
- **One project at a time per fleet session** — the CTO is designed to run one context file
  per invocation. To work on two projects simultaneously, launch two CTO agents.
- **Context files own credentials** — do not hardcode IBM i passwords, API keys, or other
  secrets anywhere except in context files, which are gitignored if they contain secrets.

## Projects this fleet works on

| Project | Context | Repo |
|---------|---------|------|
| IBMiMCP | contexts/ibmimcp.md | /Users/Sashi/Documents/projects/IBMiMCP |
| iNova | contexts/inova.md | /Users/Sashi/Documents/projects/iNova |
| Self | contexts/self-improvement.md | /Users/Sashi/Documents/projects/always-on-engineering-fleet |

## Adding a new project

Copy any context file in `contexts/` and fill in the fields for the new project.
No changes to agent files are needed — they are project-agnostic.
