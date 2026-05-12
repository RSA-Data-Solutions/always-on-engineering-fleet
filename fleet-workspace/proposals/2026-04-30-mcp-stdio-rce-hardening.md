# Proposal: Harden IBMiMCP STDIO Legacy Mode Against MCP STDIO RCE Vulnerability

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-30
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

On April 20, 2026, OX Security disclosed a critical "by-design" RCE vulnerability in Anthropic's MCP SDK affecting the STDIO transport layer across Python, TypeScript, Java, and Rust implementations. The flaw allows attackers to execute arbitrary commands on any system running a vulnerable MCP server via STDIO — granting access to databases, API keys, and system-level functions. IBMiMCP's `server.ts` explicitly supports a `legacy mode` using STDIO transport, making it directly in scope. An IBM i system is a high-value target: access via STDIO exploit could expose QSYS2 SQL execution, IFS write tools, and CL `runCommand`.

## Evidence

- [The Hacker News, Apr 20 2026](https://thehackernews.com/2026/04/anthropic-mcp-design-vulnerability.html) — "Vulnerability in Anthropic MCP design allows RCE... affects 7,000+ publicly accessible servers and 150M downloads"
- [OX Security Advisory](https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/) — "Insecure defaults in the MCP configuration on the STDIO transport interface... 10 vulnerabilities across LiteLLM, LangChain, Flowise, and IBM LangFlow"
- [HackerNoon, Apr 2026](https://hackernoon.com/mcp-security-in-2026-lessons-from-real-exploits-and-early-breaches) — "Anthropic declined to modify the protocol's architecture, citing the behavior as expected"
- IBMiMCP `src/server.ts` lines 1–15: "Supports two modes: Legacy: Single shared IBM i connection (stdio mode) / Session: Per-user connection pooling (HTTP mode)"

## Proposed change

**Type:** bug fix / security hardening
**Name / identifier:** hardenSTDIOLegacyMode

1. Add a startup warning log when STDIO (legacy) mode is used, recommending HTTP session mode for all internet-facing deployments.
2. Audit and restrict which tools are available in STDIO mode — specifically, gate `runCommand`, `runSQL`, `runSQLScript`, and all write/mutating IFS tools behind an explicit `--allow-write` flag when started in STDIO mode.
3. Add input sanitization validation in `src/tools/registry.ts` — reject tool call arguments containing shell metacharacters (`; & | $ \` etc.) before they reach the IBM i JT400 layer.
4. Update `README.md` to document the STDIO risk and recommend HTTP session mode as the production default.

## Why this project is the right place for this

IBMiMCP is the MCP server granting AI agents access to live IBM i systems; a STDIO-exploited instance bypasses all IBM i user authority and object-level security checks.

## Implementation notes

- STDIO transport is started in `src/index.ts` when `--stdio` flag is passed; gate added there
- Input sanitization can be a shared middleware in `src/tools/registry.ts` `CallToolRequestSchema` handler
- The TypeScript MCP SDK exposes `server.tool()` handler — validation added before forwarding to tool implementation
- Reference: OX Security PoC shows injection via tool `arguments` object fields

## Effort estimate

**Low** — ~60 lines across 3 files (`src/index.ts`, `src/tools/registry.ts`, `README.md`)

## Risk / caveats

- Must not break HTTP session mode (unaffected; the sanitization is additive)
- STDIO mode is used in local dev / VS Code MCP integrations — the warning should not error-exit, only warn
- Allowlist approach for metacharacters should be conservative (IBM i library/member names use only `A-Z0-9_`); SQL params should already be using parameterized queries via JT400
