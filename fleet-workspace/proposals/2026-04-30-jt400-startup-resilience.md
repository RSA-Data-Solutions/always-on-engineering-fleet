# Proposal: JT400 Connection Pool Startup Resilience — Retry + Diagnostic Tool

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-30
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

The IBMiMCP cloud instance has twice shown only 47 registered tools instead of the expected 130+, blocking every deployment gate for iNova. Root-cause analysis from both incidents (iNova issues #4 and #6) points to a silent JT400 connection pool initialisation failure at container startup: if the IBM i host (pub400.com) is unreachable when the container starts, tool classes that require a live connection fail to register, and the server starts in a degraded state with no indication to the operator. There is currently no retry logic and no diagnostic endpoint to distinguish "starting up" from "permanently broken" from "IBM i is down".

## Evidence

- iNova GitHub issue #4 (2026-04-26): "47 tools vs 130+ — probable root cause: IBMiMCP container running old image or tool module(s) failed to register at startup"
- iNova GitHub issue #6 (2026-04-28): same pattern, identical tool count, same root cause hypotheses: "If the IBM i host was unreachable when the MCP container last (re)started, some tools may not have registered. 47 tools vs 130+ is a dramatic gap suggesting a class of tools failed to initialise"
- IBM ibmi-mcp-server PR history shows similar init-failure pattern in container deployments (connection pool init silent failures are a known JT400/AS400 connectivity issue)

## Proposed change

**Type:** new feature / bug fix
**Name / identifier:** getConnectionHealth + startup retry

Two parts:

**Part A — Startup retry in `src/server/context.ts`:**
- When `initLegacyMode()` or the session pool `initSessionMode()` cannot reach the IBM i host, retry up to 3 times with 5-second backoff before marking the pool as `FAILED`
- Log a structured warning `{event: "jt400_init_retry", attempt: N, error}` on each retry
- On permanent failure after all retries: log `{event: "jt400_init_failed", tool_registration_skipped: true}` and set a server-level flag `connectionHealthy: false`

**Part B — New tool `getConnectionHealth`:**
- Parameters: none
- Returns: `{status: "ok"|"degraded"|"failed", tool_count: N, jt400_pool_size: N, ibmi_host: string, last_error: string|null, uptime_s: N}`
- Category: `system/`
- Allows operators and the iNova deployment gate (Aaron) to distinguish startup degradation from full failure without relying only on the `/info` endpoint tool count

## Why this project is the right place for this

The startup brittleness is intrinsic to IBMiMCP's JT400 pool initialisation; fixing it here eliminates a class of silent deployment failures rather than working around them in iNova's gate logic.

## Implementation notes

- `src/server/context.ts` — `initLegacyMode()` and `initSessionMode()` are the right hooks
- Retry can use simple `for (let i = 0; i < 3; i++) { try {...} catch { await sleep(5000); } }`
- `getConnectionHealth` tool reads from the `SessionContextManager` singleton; no IBM i round-trip needed if the pool already has health state
- The existing `/info` HTTP endpoint can be extended to include `connection_healthy` boolean as a quick gate check

## Effort estimate

**Medium** — ~120 lines across `src/server/context.ts` (retry), `src/tools/system/getConnectionHealth.ts` (new tool), `src/tools/system/index.ts` (register)

## Risk / caveats

- Retry adds up to 15 seconds to cold-start; document this in the startup logs
- In HTTP session mode, connection is per-user — retry applies only at pool initialisation, not per-session
- `getConnectionHealth` must not itself require a live IBM i connection (would be useless in degraded state) — read from in-memory state only
