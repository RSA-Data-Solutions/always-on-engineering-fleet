# Proposal: Per-Tool SQL Query Timeout Configuration

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-30
**Project:** IBMiMCP
**Priority:** Medium
**Status:** Awaiting CTO Review

## Problem

IBM i batch SQL queries — particularly against QSYS2 views like `HISTORY_LOG_INFO`, `ACTIVE_JOB_INFO`, and large physical files — can run for minutes under load. IBMiMCP currently has no per-tool timeout; a long-running query ties up the JT400 connection pool, blocks other tools, and eventually dies with an opaque `Connection reset` error rather than a meaningful timeout message. IBM i developers on code400.com and in the IBM ibmi-mcp-server issue tracker have raised this as a friction point: they want fast tools to stay fast and accept that slow tools are slow, but need the ability to bound execution time per call.

## Evidence

- IBM ibmi-mcp-server GitHub issue #122 (2026-03-02): "Per-tool query timeout and long-running query support" — opened by a core maintainer, labelled Enhancement, still open
- IBM ibmi-mcp-server GitHub issue #119 (2026-03-02): "MCP elicitation for interactive user workflows" — companion request; long-running queries need cancellation or confirmation flow
- Code400.com general pattern: threads asking "how do I stop a runaway RUNQRY" and "why does my SQL hang the session" are a recurring category in the system administration forum
- IBMiMCP tools `runSQLScript`, `captureAndAnalyzeJobTrace`, `captureRuntimePerformanceProfile` all execute potentially unbounded queries today

## Proposed change

**Type:** new feature
**Name / identifier:** queryTimeout parameter on SQL-executing tools

1. Add an optional `queryTimeoutSeconds` parameter (default: 30, max: 300) to all tools that execute SQL against IBM i: `runSQL`, `runSQLScript`, `runSQLWithPaging`, `explainSQL`, `checkDatabaseHealth`, `describeTable`, `listTables`.
2. Pass the timeout to the JT400 JDBC connection via `Statement.setQueryTimeout(N)` — already supported by the JT400 driver.
3. On timeout, catch `SQLException` with SQLState `HYT00` and return a structured error: `{error: "query_timeout", timeout_s: N, suggestion: "Increase queryTimeoutSeconds or narrow the WHERE clause"}`.
4. For the analysis tools (`captureRuntimePerformanceProfile`, `analyzeJobPerformance`), apply the same parameter — these are the highest-risk for runaway execution.

## Why this project is the right place for this

IBMiMCP wraps all JDBC calls; adding `setQueryTimeout` here benefits every AI agent using the server without requiring changes in the client.

## Implementation notes

- JT400's `AS400JDBCStatement` inherits `setQueryTimeout(int seconds)` from `java.sql.Statement`
- The JDBC bridge in IBMiMCP (`src/db/` or the JT400 wrapper) is the right injection point — one change applies to all tools
- SQLState `HYT00` = query execution timeout; `08S01` = communication link failure (different path)
- Default of 30 seconds is safe: all P0 tools (`getSystemStatus`, `listActiveJobs`, `listTables`) complete in <5 seconds in normal conditions

## Effort estimate

**Low** — ~40 lines in the JDBC wrapper + schema additions across ~7 tool `inputSchema` definitions

## Risk / caveats

- IBM i V7R3 and earlier may not honour `setQueryTimeout` for all query types (DDL statements) — document this
- Setting timeout too short on `runSQLScript` (multi-statement) applies per-statement, not total — clarify in tool description
- `runCommand` (CL) is not SQL; timeout there goes via `CommandCall`, different mechanism — exclude from this proposal scope
