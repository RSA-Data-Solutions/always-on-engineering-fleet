# Proposal: IBMiMCP PASE Open Source Package Discovery Tool

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-27
**Project:** IBMiMCP
**Priority:** Medium
**Status:** Awaiting CTO Review

## Problem

IBM i developers regularly struggle to discover what PASE (yum/RPM)
packages are available, installed, or upgradeable on their system.
The only current workflows are: SSH in and run `yum list` manually, or
browse IBM's static OSS docs page. Neither is accessible from an AI
coding session. Developers working in iNova's agentic IDE have no way
to ask "what Python packages are available?" or "is Node 22 in the
yum repo?" without leaving the IDE.

## Evidence

- **Richard Schoen's blog** (blog.richardschoen.net, April 2026):
  "I Can't Find My IBM i Open Source Packages" — documents the
  confusion around package naming, repo URLs, and version availability
  on PASE. Specifically calls out that `yum list available` output is
  overwhelming and that developers need a filtered, searchable view.
- IBM i OSS community pattern (ibm.github.io/ibmi-oss-resources): IBM
  documents packages at a high level but provides no queryable API.
  Community Slack (#ibmi-oss) regularly sees "does yum have X?" threads.
- No existing IBMiMCP tool covers PASE package management — the current
  toolset has IFS, SQL, job, and source tools but nothing for the OSS
  package layer.

## Proposed change

**Type:** new tool
**Name / identifier:** `listAvailablePASEPackages`

A new IBMiMCP tool that wraps `yum list` (available, installed, or
updates) via `runCommand` internals and returns structured JSON.

**Parameters:**
- `filter` (string, optional): package name prefix or glob, e.g.
  `"python3*"` or `"nodejs*"`
- `state` (enum, optional, default `"installed"`):
  `"installed"` | `"available"` | `"updates"`
- `limit` (number, optional, default 50): max packages returned

**Example use:**
```
listAvailablePASEPackages({ filter: "nodejs", state: "available" })
→ { packages: [ { name: "nodejs22", version: "22.3.0", repo: "ibm" }, ... ] }
```

## Why this project is the right place for this

IBMiMCP is the authoritative IBM i tool layer for iNova. PASE package
discovery is a direct IBM i system operation and a natural extension of
the existing `system/` category.

## Implementation notes

```bash
# Underlying shell command (via PASE QShell or CL QSHELL cmd):
yum list {state} {filter} 2>/dev/null
# Parse output: "package.arch  version  repo"
```

Alternatively use `QSYS/QSH CMD('yum list ...')` via the existing
`runCommand` SQL bridge, or call PASE directly if the server process
runs in PASE context.

Output format:
```json
{
  "state": "installed",
  "filter": "python3*",
  "count": 4,
  "packages": [
    { "name": "python39", "version": "3.9.18", "arch": "ppc64", "repo": "ibm" }
  ]
}
```

Place in `src/tools/system/listAvailablePASEPackages.ts`.

## Effort estimate

**Low** — ~80 lines. Parse the `yum list` text output (3-column TSV);
no new SQL or JDBC required. The command execution pattern is already
established by `runCommand`.

## Risk / caveats

- Requires `yum` to be installed in PASE (standard on V7R3+; confirm
  minimum OS version).
- `yum list available` can be slow (~10–30s) on slow networks — add
  a 60-second timeout and document it.
- `yum list updates` requires network access to the IBM OSS repo;
  offline systems will return an error — handle gracefully.
