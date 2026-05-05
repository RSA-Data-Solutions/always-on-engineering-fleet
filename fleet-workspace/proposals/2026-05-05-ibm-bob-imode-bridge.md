# Proposal: getIBMiBobContext — IBM Bob iMode Bridge Context Bundle

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-05
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM Bob hit general availability on April 28, 2026 — but its flagship IBM i feature, "iMode" (direct access to QSYS source members and libraries), shipped with no release date. Multiple IBM i developers have publicly stopped using Bob's pre-release versions specifically because it cannot access source files stored in traditional source physical files or the IFS. The community is explicitly waiting for a bridge. IBMiMCP already holds all the data Bob needs; it just doesn't surface it in a single, context-efficient bundle.

## Evidence

- [IT Jungle, Dec 2025] "Bob cannot yet work directly with your IBM i, whether source lives in traditional source physical files or in the IFS… this functionality will come through iMode with no release date as of yet."
- [IT Jungle, Apr 6 2026 — "Bob 1.0 Users Bugged By Lack Of One Feature"] Multiple users described stopping use of pre-release Bob due to the absence of QSYS integration. One IBM i professional stated: "I stopped using the pre-release version since it didn't utilize IBM i connections, including the ability to work with source files and libraries."
- [IBM Bob GA announcement, Apr 28 2026] iMode still not included in GA release; IBM Premium Package for i expected by end of Q2 2026.
- [freschesolutions.com / community posts] "That future capability is what many developers… are genuinely excited to see."
- The search volume pattern (multiple publications covering the same single gap within one week of Bob's GA) confirms this as a repeated community pain point, not anecdote.

## Proposed change

**Type:** new tool
**Name / identifier:** `getIBMiBobContext`

A single MCP tool that aggregates all the IBM i context an AI agent needs for one program or source member into one structured response, formatted for minimal token usage. This bridges Bob's iMode gap today: any Bob user who wires their MCP config to IBMiMCP gets immediate IBM i source access without waiting for iMode.

**Parameters:**
- `library` (string, required) — QSYS library name
- `object` (string, required) — program, module, or service program name
- `memberType` (string, optional) — source member type filter (e.g. `RPGLE`, `CLLE`, `SQLRPGLE`)
- `includeJobLog` (boolean, optional, default false) — include most recent compile/run job log entries
- `maxSourceLines` (number, optional, default 500) — cap source lines returned to keep context manageable

**Example use:**
> "Bob, analyse the CUSTINQ program in MYLIB and tell me what it does."
> → tool call: `getIBMiBobContext(library="MYLIB", object="CUSTINQ", includeJobLog=true)`
> → returns: source member text, last compilation errors (from QSYS2.OBJECT_STATISTICS), direct object dependencies (from getObjectDependencyChain), last 20 job log entries

**Response shape:**
```json
{
  "object": "CUSTINQ",
  "library": "MYLIB",
  "source": { "member": "CUSTINQ", "type": "RPGLE", "lines": [...] },
  "lastCompileErrors": [...],
  "dependencies": { "programs": [...], "files": [...] },
  "recentJobLog": [...]
}
```

## Why this project is the right place for this

IBMiMCP already contains the four building blocks (source tools, SQL tools, job tools, dependency tools). This proposal assembles them into a single ergonomic call that makes IBMiMCP the de-facto Bob iMode substitute until IBM ships the real thing.

## Implementation notes

- Source: `getSourceMember` + `searchSourceMembers` (existing)
- Compile errors: `QSYS2.OBJECT_STATISTICS` or `getCompilationErrors` (existing)
- Dependencies: `getObjectDependencyChain` (existing SQL tool)
- Job log: `getJobLog` with filter on object name (existing)
- New tool file: `src/tools/source/getIBMiBobContext.ts` — orchestrates the above, no new SQL queries needed
- Must respect `maxSourceLines` cap to avoid flooding LLM context windows

## Effort estimate

**Medium** — ~150 lines; orchestrates 4 existing tools; adds one new file in `source/` category.

## Risk / caveats

- Source members may be very large; `maxSourceLines` cap is essential.
- `getObjectDependencyChain` may be slow on deep dependency trees; consider `maxDepth: 2` default.
- Name collision: check Bob's own MCP tool naming conventions to avoid conflicts if users run both Bob's shell MCP and IBMiMCP simultaneously.
