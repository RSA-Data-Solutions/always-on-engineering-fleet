# Proposal: ACP/A2A Protocol Convergence — IBMiMCP Compatibility Tracking

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-05
**Project:** IBMiMCP
**Priority:** Medium
**Status:** Awaiting CTO Review

## Problem

IBM Think 2026 (Boston, May 4–7) announced that Anthropic's MCP, IBM's Agent Communication Protocol (ACP), and Google's Agent-to-Agent (A2A) protocol have merged under the Linux Foundation's new Agentic AI Foundation. IBMiMCP currently implements MCP only. IBM's own watsonx.data 2.3.2 (announced today at Think 2026) ships a managed MCP server that is already positioned within the ACP/MCP unified namespace. If the merged spec introduces breaking transport or discovery changes, IBMiMCP will be unable to serve IBM watsonx agents or Google agents — exactly the enterprise accounts iNova targets.

## Evidence

- [IBM Think 2026 announcements, May 4–5 2026] "Agent protocols have converged: Anthropic's MCP, IBM's ACP, and Google's A2A merged under the Linux Foundation's Agentic AI Foundation."
- [IBM watsonx.data 2.3.2, May 2026] "IBM introduces a managed MCP server that exposes data platform capabilities as standardized, discoverable tools, enabling agents to securely and dynamically interact with data." — IBM is now a first-party MCP server publisher; IBMiMCP competes/complements in that space.
- [2026 MCP Roadmap, modelcontextprotocol.io] MCP 2025-11-25 compliance is flagged as an open issue (upstream IBM ibmi-mcp-server issue #4240) — indicating existing IBM i MCP servers are not fully compliant with the current spec, let alone the merged spec.
- The convergence announcement was made yesterday (May 4). It has not yet had time to propagate to community complaints, but the strategic impact on IBMiMCP is immediate.

## Proposed change

**Type:** agent improvement + future new feature tracking
**Name / identifier:** `acp-a2a-compat` (tracking task) + `getAgentCapabilities` (new tool, if CTO approves)

**Phase 1 (agent improvement — low effort, high value):**
Update `agents/ram.md` and `agents/dhira.md` to include a standing monitor:
- Dhira checks the Linux Foundation Agentic AI Foundation spec releases monthly
- Ram's context file for IBMiMCP tracks protocol compliance as a P0 gate on all new releases

**Phase 2 (new tool — medium effort, if approved):**
Add a `getAgentCapabilities` endpoint to IBMiMCP that returns the server's protocol compliance metadata in the unified spec format. This allows ACP/A2A-speaking agents (IBM watsonx, Google) to discover IBMiMCP's tools via the merged registry protocol, not just via MCP tool listing.

**For the new tool:**
- Parameters: none (it's a discovery/metadata endpoint)
- Returns: JSON manifest in Linux Foundation Agentic AI Foundation discovery format
- Maps each IBMiMCP tool to its ACP/A2A capability descriptor

## Why this project is the right place for this

IBMiMCP is the only production MCP server for IBM i. If the merged protocol spec becomes the enterprise standard (IBM is already aligning watsonx.data to it), IBMiMCP must comply to remain the default choice for IBM customers building agents against their IBM i.

## Implementation notes

- The Linux Foundation Agentic AI Foundation spec is in draft as of Think 2026. Implementation should wait for a stable draft before coding.
- Phase 1 (fleet agent file updates) can be done immediately.
- Phase 2 requires reading the unified spec discovery format — likely a `.well-known/agent` endpoint returning a capability manifest JSON.
- IBM ACP spec is at `https://agentcommunicationprotocol.dev/` (IBM's published draft).

## Effort estimate

**Phase 1:** Low — ~20 lines of agent file edits
**Phase 2:** Medium — ~100 lines; new discovery endpoint; requires spec reading first

## Risk / caveats

- The merged spec is in draft; implementing too early may require rework.
- The CTO may choose to defer Phase 2 until the spec stabilises (recommended).
- Phase 1 (fleet agent monitoring update) has zero risk and should proceed regardless.
