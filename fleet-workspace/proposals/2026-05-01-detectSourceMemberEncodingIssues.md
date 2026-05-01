# Proposal: detectSourceMemberEncodingIssues — CCSID / Encoding Audit for Source Members

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-01
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i source members with non-ASCII characters in their names — such as the GBP pound sign
`£`, euro `€`, or other EBCDIC-mapped glyphs — cannot be opened or edited by VS Code IBM i
tooling. The same failure mode surfaces in IBMiMCP's `getSourceMember` and `updateSourceMember`
tools: a member name that is valid on IBM i but contains a CCSID-37 character outside ASCII
will either fail silently, return an empty result, or corrupt the content during round-trip
encoding. Developers have no tool to audit a source file for affected members before attempting
to read or migrate them.

## Evidence

- [codefori/vscode-ibmi #3169 — "Cannot open source members with '£' in name" (DrIce99, Apr 24 2026)](https://github.com/codefori/vscode-ibmi/issues/3169)
  — *"The member shows correctly in the object browser listing but clicking it throws an error.
  The display seems to use EBCDIC mapping but the open path passes the raw Unicode character
  and the server rejects it."*
- [codefori/vscode-ibmi #3167 — "Saving DDL to IBM i adds backslash to code" (erk48188, Apr 23 2026)](https://github.com/codefori/vscode-ibmi/issues/3167)
  — Related encoding corruption: content written from a UTF-8 client is mangled when stored
  via CCSID-37 paths without proper transcoding.
- Pattern: Two distinct issues in two days from different users — encoding round-trip is an
  active pain point for modernisation workflows.

## Proposed change

**Type:** new tool  
**Name / identifier:** `detectSourceMemberEncodingIssues`

Scans a source physical file (SRCPF) and returns a list of members whose names or content
contain characters that may not survive UTF-8 ↔ EBCDIC round-trip transcoding. Read-only.

**Parameters:**
- `library` (string, required) — library name
- `sourceFile` (string, required) — source physical file name (e.g. `QRPGLESRC`)
- `checkContent` (boolean, optional, default false) — if true, reads a sample of each member
  and flags content that contains EBCDIC bytes with no clean UTF-8 mapping

**Example use:**
> "Which members in MYLIB/QRPGLESRC have names or content that might break when I migrate them to IFS?"
```json
{ "tool": "detectSourceMemberEncodingIssues", "args": { "library": "MYLIB", "sourceFile": "QRPGLESRC", "checkContent": false } }
```

**Expected output:**
```json
{
  "library": "MYLIB",
  "sourceFile": "QRPGLESRC",
  "totalMembers": 42,
  "flaggedMembers": [
    {
      "name": "PAY£CALC",
      "issue": "name_non_ascii",
      "detail": "Character '£' (U+00A3) maps to EBCDIC 0x4A; may not survive round-trip via ASCII path"
    }
  ],
  "clean": 41,
  "flagged": 1
}
```

## Why this project is the right place for this

IBMiMCP is the primary tool for AI-assisted IBM i source migration. Developers using it to
modernise RPGLE/COBOL codebases will hit this issue before writing a single line of new code.

## Implementation notes

- Member listing: `SELECT SYSTEM_TABLE_MEMBER AS MEMBER_NAME FROM QSYS2.SYSPARTITIONSTAT WHERE SYSTEM_TABLE_SCHEMA = :lib AND SYSTEM_TABLE_NAME = :file`
- Non-ASCII check: for each member name, test `Buffer.from(name, 'utf8')` vs code-point range.
- Content sample (when `checkContent: true`): use `getSourceMember` internally, scan for
  replacement characters (U+FFFD) or byte sequences that indicate transcoding failure.
- Target file: `src/tools/source/detectSourceMemberEncodingIssues.ts`

## Effort estimate

**Low** — ~80 lines. One SQL query for member list, one loop for name validation, optional
content sample read.

## Risk / caveats

- `checkContent: true` can be slow on large source files (hundreds of members). Cap at 200
  members or add a `maxMembers` parameter.
- CCSID depends on the source file's declared encoding — this tool assumes CCSID 37 (standard
  US English IBM i). Sites running CCSID 273 (German) or similar will need a follow-up.
