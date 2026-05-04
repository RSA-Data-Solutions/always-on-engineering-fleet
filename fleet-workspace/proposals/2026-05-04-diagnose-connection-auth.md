# Proposal: diagnoseConnectionAuth — IBM i MCP Connection & Auth Diagnostics

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-04
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i MCP users frequently misconfigure their connection credentials, particularly when using token-based (Bearer) authentication. The upstream IBM ibmi-mcp-server has an open, unresolved issue (#77, Dec 2025) documenting that users hit a cryptic validation error — "DB2i_USER is required" — even when they are correctly using token auth. A companion issue (#137, Mar 2026) reports that the default .env-file credential loading creates security risk in production because the docs don't adequately warn users. IBMiMCP surfaces the same auth setup friction, and currently provides no tool to help a user or agent self-diagnose a connection problem.

## Evidence

- [IBM/ibmi-mcp-server #77](https://github.com/IBM/ibmi-mcp-server/issues/77) — "DB2i_USER is required for IBM i connections" error when using token auth; root cause is a validator schema flaw; open since Dec 2025 with no comment or fix.
- [IBM/ibmi-mcp-server #137](https://github.com/IBM/ibmi-mcp-server/issues/137) — ".env file by default" security concern: docs encourage .env usage without warning it's development-only; open Mar 2026.
- iNova Issues #4 and #6 — Deployment gate failures where `server_reachable: false` from orchestrator while the server is externally live suggest auth/URL misconfiguration between internal containers is a recurring blind spot.

## Proposed change

**Type:** new tool
**Name / identifier:** `diagnoseConnectionAuth`

A read-only diagnostic tool that tests the active IBM i MCP connection configuration and reports the auth method in use, connectivity status, and any detectable misconfiguration. Returns structured results an agent can act on.

**Parameters:**
- `testQuery` (boolean, optional, default: true) — if true, run a lightweight `SELECT 1 FROM SYSIBM.SYSDUMMY1` to verify DB2 connectivity beyond TCP
- `reportAuthMethod` (boolean, optional, default: true) — report which auth method is active (token, username/password, or unset)

**Example use:**
> "Is my IBMiMCP connection working? Check the auth config."
> → calls `diagnoseConnectionAuth` → returns `{ auth_method: "token", tcp_reachable: true, db2_query_ok: true, warnings: [] }`

**Return fields:**
- `auth_method`: `"token"` | `"username_password"` | `"unconfigured"`
- `tcp_reachable`: boolean
- `db2_query_ok`: boolean (if testQuery true)
- `response_time_ms`: number
- `warnings`: string[] — e.g. `[".env file detected: not recommended for production"]`
- `errors`: string[] — e.g. `["DB2i_USER set to empty string; omit it entirely for token auth"]`

## Why this project is the right place for this

IBMiMCP is the connection layer between AI agents and IBM i; connection diagnostics belong here, not in the calling agent.

## Implementation notes

- Auth method detection: check whether `DB2i_USER`/`DB2i_PASS` env vars are set and non-empty vs. whether a Bearer token is present in request headers
- TCP test: attempt a `mapepire-js` pool connection with a 3 s timeout
- DB2 test: `SELECT 1 FROM SYSIBM.SYSDUMMY1` via the pool
- .env detection: check `process.env` for the `DOTENV_CONFIG_PATH` flag or whether dotenv was loaded
- Lives in `src/tools/system/` alongside `getSystemStatus`

## Effort estimate

**Low** — ~80 lines; reads env vars and runs one lightweight SQL query; no new dependencies.

## Risk / caveats

- Token introspection requires knowing the transport in use (HTTP vs stdio); keep it best-effort with a graceful unknown fallback.
- Do not log or return credential values — only report presence/absence.
