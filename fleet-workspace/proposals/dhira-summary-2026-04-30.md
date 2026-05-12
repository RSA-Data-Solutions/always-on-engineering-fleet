# Research Summary — 2026-04-30

Project: IBMiMCP
Searched: r/IBMi (Reddit new), code400.com forums, GitHub (IBM/ibmi-mcp-server issues, rsa-data-solutions/ibmimcp, rsa-data-solutions/inova), Hacker News / security news (MCP vulnerability coverage), X/security blogs, iNova issue tracker

Top finding: A critical "by-design" MCP STDIO transport RCE vulnerability was disclosed on April 20, 2026 (OX Security / Hacker News) affecting 7,000+ MCP servers including IBM tooling — IBMiMCP's legacy STDIO mode is directly in scope and needs hardening.

Proposals submitted: 4 (see index.md).

Highest priority: hardenSTDIOLegacyMode — IBMiMCP's STDIO legacy mode is vulnerable to the actively-publicised April 2026 MCP RCE class; IBM i systems are high-value targets and the fix is low-effort (~60 lines).
