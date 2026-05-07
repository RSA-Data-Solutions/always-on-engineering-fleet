# Proposal: compareSourceMembers — Source Member Content Diff

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-07
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i developers frequently need to compare source member content between two libraries
(e.g., DEVLIB vs. PRODLIB) or between two members within the same source file before
promoting changes. Today they must pull both members manually, paste into an editor, and
diff by eye. The current toolset has `compareEnvironments` (compares object existence, not
source content) and `getSourceMemberHistory` (change log, not content diff) — neither
gives a line-by-line textual diff. This forces context switches out of the AI-assisted
workflow every time a developer wants to verify what changed before promoting code.

## Evidence

- [IT Jungle, 2021-04-19] "Guru: Compare Pieces of Source Members" — demonstrates that
  source member comparison is a repeated enough need that IT Jungle covered it as a
  standalone tutorial; the technique described is manual and error-prone.
- [blog.richardschoen.net, 2024-11] "Simple IBM i Source Member Version Control" — developer
  explicitly describes needing to compare member versions as part of a basic version control
  workflow; no tool automates this today.
- [ibm.com/community, 2026] Multiple threads in IBM i modernization discussions cite the
  source-to-IFS migration path as the number-one friction point; knowing *what differs*
  between the PF-SRC and IFS copy is the first question that stalls the migration.
- No open-source MCP tool (IBM/ibmi-mcp-server, IBMiMCP) currently provides this capability
  as of May 2026.

## Proposed change

**Type:** new tool
**Name / identifier:** `compareSourceMembers`

Returns a unified diff of two source members. The caller specifies two member locations
(library/file/member pairs) and the tool reads both, produces a line-level diff, and returns
the diff as a structured result plus a human-readable summary.

**Parameters:**
- `fromLibrary` (string, max 10) — library of the baseline member
- `fromFile` (string, max 10) — source physical file of the baseline
- `fromMember` (string, max 10) — baseline member name
- `toLibrary` (string, max 10) — library of the target member
- `toFile` (string, max 10) — source physical file of the target
- `toMember` (string, max 10) — target member name
- `contextLines` (number, optional, default 3) — context lines around each change
- `ignoreWhitespace` (boolean, optional, default false) — ignore leading/trailing whitespace

**Example use:**
> "Show me what changed in QGPL.QRPGLESRC.ORDPROC compared to PRODLIB.QRPGLESRC.ORDPROC"
→ `compareSourceMembers({ fromLibrary: "QGPL", fromFile: "QRPGLESRC", fromMember: "ORDPROC", toLibrary: "PRODLIB", toFile: "QRPGLESRC", toMember: "ORDPROC" })`

**Output:**
```json
{
  "success": true,
  "from": "QGPL/QRPGLESRC.ORDPROC",
  "to": "PRODLIB/QRPGLESRC.ORDPROC",
  "identical": false,
  "addedLines": 3,
  "removedLines": 1,
  "changedChunks": 2,
  "unifiedDiff": "--- QGPL/QRPGLESRC.ORDPROC\n+++ PRODLIB/QRPGLESRC.ORDPROC\n@@...",
  "summary": "3 lines added, 1 line removed across 2 chunks"
}
```

## Why this project is the right place for this

IBMiMCP is the primary MCP tool layer for IBM i source operations; completing the
source management suite with a diff capability is a natural fit alongside `copySourceMember`,
`getSourceMemberHistory`, and `promoteObjects`.

## Implementation notes

- Read both members using `getSourceMember`-style SQL alias technique:
  `CREATE ALIAS ... FOR lib.file(member)` then `SELECT SRCDTA FROM alias ORDER BY RRNO`
- Store lines in-memory, apply Myers diff algorithm (standard, ~80 lines of TypeScript)
- Return unified diff string + structured counts
- Clean up both aliases in a `finally` block
- QSYS2.SYSMEMBERSTAT can be queried first to verify both members exist before reading;
  return a clear error if either member is not found

## Effort estimate

**Medium** — ~150 lines: SQL alias reads (~30 lines already proven in other tools),
Myers diff implementation (~80 lines), output formatting (~30 lines).

## Risk / caveats

- Very large members (>10,000 lines) may be slow; add a `maxLines` guard (default 5000)
  and return a warning if truncated
- CCSID conversion: both reads go through JDBC which handles EBCDIC→UTF-8; diff result
  will be UTF-8 clean
- Members in different source file types (e.g., RPGLE vs. CLLE) are valid to compare
  (text is text); no type restriction needed
