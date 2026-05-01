# Proposal: diagnoseMapepiReconnect — Mapepire Connection Pool Health Diagnostic

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-01
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i developers are reporting slow Mapepire connection times that cause MCP tool calls to
time out or feel sluggish. Because IBMiMCP uses Mapepire as its sole database gateway, any
connection pool degradation silently degrades every SQL-backed tool — but there is currently
no tool to diagnose the pool state without reading server logs. Developers have no way to ask
"why is my tool call slow?" and get a structured answer.

## Evidence

- [codefori/vscode-ibmi #3170 — "Mapapire connection time is slow" (bobcozzi, Apr 24 2026)](https://github.com/codefori/vscode-ibmi/issues/3170)
  — *"Connection takes 4–8 seconds on the first call after idle. Subsequent calls are fast.
  Something in the Mapepire pool is not keeping connections warm."*
- [IBM/ibmi-mcp-server #122 — per-tool query timeout (Mar 2026)](https://github.com/IBM/ibmi-mcp-server/issues/122)
  — Community framing: global 30 s timeout kills legitimate long-running operations because
  there is no visibility into whether the delay is connection setup or query execution.
- iNova issue #6 / #4 — IBMiMCP cloud instance stuck at 47 tools: root cause hypothesis 3
  is JT400 connection pool failure at startup. No diagnostic surface exists to confirm this.

## Proposed change

**Type:** new tool  
**Name / identifier:** `diagnoseMapepiReconnect`

A read-only diagnostic tool that probes the Mapepire connection pool and returns structured
health data. Does not modify any IBM i state.

**Parameters:**
- `includeQueryTest` (boolean, optional, default true) — if true, executes a trivial
  `SELECT 1 FROM SYSIBM.SYSDUMMY1` to measure end-to-end query latency

**Example use:**
> "Why is IBMiMCP responding slowly? Are the Mapepire connections healthy?"
```json
{ "tool": "diagnoseMapepiReconnect", "args": { "includeQueryTest": true } }
```

**Expected output:**
```json
{
  "pool_size": 5,
  "active_connections": 2,
  "idle_connections": 3,
  "pending_requests": 0,
  "connection_acquire_ms": 12,
  "query_round_trip_ms": 34,
  "last_error": null,
  "diagnosis": "healthy"
}
```

## Why this project is the right place for this

IBMiMCP is the only tool in the fleet with direct Mapepire pool access; no other layer can
expose these internals.

## Implementation notes

- The Mapepire pool is managed in `src/db/pool.ts` (or equivalent). The pool object
  typically exposes `totalCount`, `idleCount`, `waitingCount` via node-postgres-style APIs.
- Connection acquire time: wrap `pool.acquire()` in a `Date.now()` delta.
- Query latency: `await pool.query('SELECT 1 FROM SYSIBM.SYSDUMMY1')` with timing.
- Expose tool under `src/tools/system/diagnoseMapepiReconnect.ts`.

## Effort estimate

**Low** — ~60 lines. Reads pool state + runs one trivial query + formats JSON.

## Risk / caveats

- Pool API shape depends on the Mapepire client library version — verify field names before
  implementing.
- `includeQueryTest: true` requires a live IBM i connection; if the pool is fully broken,
  the query step will fail and should be caught and reported rather than thrown.
