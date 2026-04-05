# Project Context — Self-Improvement

This context file tells the engineering fleet to target its own repo — improving the
agent instruction files, context files, and skill over time based on past run experience.

---

## Project identity

| Field | Value |
|-------|-------|
| Name | always-on-engineering-fleet (self) |
| Description | The fleet improves its own agent instructions, context files, and SKILL.md |
| Repo path | `/Users/Sashi/Documents/projects/always-on-engineering-fleet` |
| Language | Markdown (agent instructions, context files) |
| Test runner | Consistency checker (see below) |

---

## Commands

```yaml
install_command:  ""   # nothing to install
test_command:     "python3 scripts/validate_agents.py"
build_command:    ""
```

> The validation script (`scripts/validate_agents.py`) is created and maintained by the
> fleet itself. On first run (if it doesn't exist), create it as described below.

---

## Validation script bootstrap

If `scripts/validate_agents.py` does not exist, the SE agent should create it. It should:

1. Check that all agent files referenced in `SKILL.md` exist
2. Check that all context files referenced in `SKILL.md` and `CLAUDE.md` exist
3. Check that each agent file has the required sections (defined in a simple checklist)
4. Check that each context file has the required fields (`repo_path`, `test_command`,
   `install_command`, `environment`, `push_remote`, `research_communities`, `human_scope`)
5. Check for obvious contradictions (e.g. a rule in cto.md that conflicts with se.md)
6. Print `PASS [check_name]` / `FAIL [check_name]: reason` — same format as run_tests.py
7. Exit 0 if all pass, exit 1 if any fail

---

## Environment

None — this is a pure markdown repo. No services to start, no credentials needed.

---

## Git remote

```yaml
push_remote:  origin
push_branch:  main
github_repo:  https://github.com/RSA-Data-Solutions/always-on-engineering-fleet
```

---

## What counts as a "bug" in self-improvement mode

The QA Engineer reports failures from the validation script, plus any of these patterns
found by manual review:

- **Broken reference** — a file path, section, or field mentioned in one agent file
  doesn't exist (e.g. `agents/ram.md` says to read `contexts/ibmimcp.md` but the file
  moved)
- **Stale instruction** — an instruction references a command, column name, or tool that
  no longer exists in the target project
- **Missing edge case** — a past fleet run summary documents a situation the agent
  instructions didn't anticipate (and the agent got confused)
- **Unclear instruction** — an agent repeatedly made the same mistake on a step, suggesting
  the instruction was ambiguous
- **Missing project support** — a new project was added to the fleet but the agents lack
  project-specific guidance for it

---

## What Dhira does in self-improvement mode

Dhira reviews:
1. All files in `fleet-workspace/` (past summaries, QA reports, iteration logs)
2. Agent design literature and the Claude Agent SDK docs (via web search)
3. Past proposal outcomes — did what was built actually deliver value?

Dhira proposes:
- Clarifications to agent instructions
- New sections in agent files (e.g. "guidance for project X")
- Improvements to the proposal format or review workflow
- New validation checks for the validator script
- Restructuring that would reduce confusion between agents

---

## Known quirks and constraints

- Agent files are Markdown — the SE edits them with precision, not wholesale rewrites
- Do not change the fundamental role of any agent (CTO as orchestrator, etc.)
- Do not remove existing instructions unless they are demonstrably wrong
- Commit message format: `improve: agents/<file> — <what changed>`
- All changes go through QA validation before push

---

## Human scope (default)

Unless overridden at fleet launch:
- Fix any validation failures
- Improve clarity of existing instructions based on past run evidence
- Do not restructure the repo layout
- Do not rename agent files
- Do not add a new project context without human approval

---

## Research communities (for Dhira)

- Past fleet run summaries in `fleet-workspace/`
- Claude Agent SDK documentation
- Multi-agent systems research (web search)
- LLM agent prompt engineering literature

**Research focus:** Evidence-based improvements. Only propose changes grounded in observed
failures or clearly documented best practices — not speculative rewrites.
