# Proposal: IBM BOB 1.0 MCP Interoperability — Tool Annotations for Bob-Compatible Discovery

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-30
**Project:** IBMiMCP
**Priority:** Medium
**Status:** Awaiting CTO Review

## Problem

IBM shipped BOB 1.0 GA on March 24, 2026 with native MCP support, positioning it as the AI coding tool for IBM i RPG/COBOL developers. BOB uses MCP to discover and call tools from connected servers. IBMiMCP is the richest IBM i MCP server available, but its tool descriptions are written generically for any MCP client. IBM i developers using Bob alongside iNova/IBMiMCP are finding that Bob's AI struggles to choose the right tool because tool names and descriptions don't follow the vocabulary Bob's prompt-engineering expects (e.g., Bob uses "compile", "diagnose", "explain" as natural-language anchors, while IBMiMCP uses camelCase technical names like `compileSQLRPGLE`, `analyzeJobAbendAndCrash`). The result: Bob either doesn't suggest IBMiMCP tools or picks wrong ones.

## Evidence

- [IT Jungle, Mar 2 2026](https://www.itjungle.com/2026/03/02/ibm-gets-bob-1-0-off-the-ground/) — "Bob supports MCP... will allow customers to plug Bob into all sorts of other tools... Bob can explain, refactor, generate, transform, and test code in RPG, RPGLE, SQLRPGLE, CL, DDS"
- iNova product positioning (`inovaide.com`): "iNova IDE connects to IBM i with MCP-powered AI tools"
- IBM BOB 1.0 targets the same IBM i developer audience as iNova/IBMiMCP; no documented interop guide exists
- Community expectation from IBM i developer forums: tools from one IBM i MCP server should be usable from any MCP-compatible AI IDE, including Bob

## Proposed change

**Type:** new feature / documentation
**Name / identifier:** bobCompatibleToolAnnotations

1. Add MCP tool `annotations` (per MCP spec `toolAnnotations` field) to each IBMiMCP tool that map to Bob's natural language categories: `readOnlyHint: true/false`, `destructiveHint: true/false`, `idempotentHint: true/false`.
2. Enrich `description` fields on the 10 most-used tools (`compileRPGLE`, `compileSQLRPGLE`, `runSQL`, `listActiveJobs`, `getJobLog`, `getSystemStatus`, `getJobStatus`, `listTables`, `describeTable`, `runCommand`) with a one-sentence "Bob-friendly" natural language lead that uses Bob's vocabulary.
3. Add a `docs/BOB-INTEGRATION.md` guide with: how to register IBMiMCP as a Bob MCP tool server, example prompts that work well, and which tools are read-only vs destructive.

## Why this project is the right place for this

IBMiMCP is the MCP tool server; improving its tool metadata and documentation benefits all MCP clients (Bob, Claude, VS Code Copilot) without requiring changes in those clients.

## Implementation notes

- MCP spec `toolAnnotations` object: `{readOnlyHint, destructiveHint, idempotentHint, openWorldHint, title}` — already supported in `@modelcontextprotocol/sdk` TypeScript types
- Tool annotations are added in each tool's `server.tool(name, description, inputSchema, annotations, handler)` call or via the `ListToolsResponse` schema
- "Bob-friendly" descriptions: "Compile an RPGLE source member on IBM i and return any compilation errors" is better than just "Compile RPGLE"
- Bob's MCP integration is documented at IBM's Bob product docs (IBM Docs, search "Bob MCP")

## Effort estimate

**Low** — ~80 lines across tool definition files for annotations; ~200 words for BOB-INTEGRATION.md

## Risk / caveats

- `readOnlyHint: false` on `runCommand` and `runSQL` (with DML) is important — incorrect annotations could mislead Bob into running destructive tools in read-only contexts
- Bob's MCP client behaviour is not fully documented; annotations may not be consumed yet in Bob 1.0 — propose as "forward-compatible" additions regardless
- Does not require access to a Bob license for implementation; testable via the MCP tools/list response
