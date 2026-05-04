# Proposal: inspectTemporaryStorage — Temporary Storage Inspector

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-04
**Project:** IBMiMCP
**Priority:** Medium
**Status:** Awaiting CTO Review

## Problem

Querying IBM i temporary storage when none is currently allocated causes an unhandled crash in the IBM MCP ecosystem. The upstream IBM/ibmi-mcp-server has an open issue (#52, Dec 2025) documenting a `TypeError: Cannot read properties of undefined (reading 'getRunningCount')` that occurs inside mapepire-js when the temporary storage query returns no active rows. IBMiMCP has no temporary storage tool at all — developers who want to inspect storage allocation have no MCP tool to reach for, and if they try to query QSYS2 storage views directly via `runSQL`, they hit the same crash pattern.

## Evidence

- [IBM/ibmi-mcp-server #52](https://github.com/IBM/ibmi-mcp-server/issues/52) — "TypeError querying unnamed temporary storage" — `Cannot read properties of undefined (reading 'getRunningCount')` when no temp storage is active; root cause is missing null guard before accessing pool properties; open since Dec 2025.
- IBMiMCP `src/tools/system/` directory has no temporary storage tool — confirmed by directory scan today.

## Proposed change

**Type:** new tool
**Name / identifier:** `inspectTemporaryStorage`

A null-safe tool that queries QSYS2 temporary storage views and returns a structured summary, gracefully handling the case where no temporary storage is currently allocated.

**Parameters:**
- `jobName` (string, optional) — filter to a specific job name pattern (SQL LIKE syntax)
- `minSizeKb` (number, optional) — only return entries above this threshold
- `maxRows` (number, optional, default: 50)

**Example use:**
> "Is any job using excessive temporary storage right now?"
> → calls `inspectTemporaryStorage` → returns `{ active: false, message: "No temporary storage currently allocated" }` or a list of active allocations

**Return fields:**
- `active`: boolean — false if no temp storage currently allocated
- `message`: string — human-readable summary
- `allocations`: array of `{ job_name, user, pool_name, size_kb, object_type }` (empty array if none)
- `total_allocated_kb`: number (0 if none)

## Why this project is the right place for this

IBMiMCP is the operator-facing IBM i diagnostics layer; storage inspection fits the `system/` category alongside `getDiskUsage` and `getMemoryPoolAnalysis`.

## Implementation notes

- Query: `SELECT JOB_NAME, AUTHORIZATION_NAME, POOL_NAME, TEMPORARY_STORAGE FROM TABLE(QSYS2.ACTIVE_JOB_INFO(RESET_STATISTICS => 'NO')) X WHERE TEMPORARY_STORAGE > 0`
- Wrap result access in null guards: `if (!rows || rows.length === 0) return { active: false, ... }`
- Lives in `src/tools/system/inspectTemporaryStorage.ts`
- The null guard pattern fixes the upstream crash class at the IBMiMCP layer, making this tool safe regardless of allocation state

## Effort estimate

**Low** — ~70 lines; single QSYS2 query with null-safe result handling.

## Risk / caveats

- `QSYS2.ACTIVE_JOB_INFO` requires `*JOBCTL` special authority or equivalent; document in tool description.
- V7R3 and earlier may not have `TEMPORARY_STORAGE` column — add a V7R4+ note.
