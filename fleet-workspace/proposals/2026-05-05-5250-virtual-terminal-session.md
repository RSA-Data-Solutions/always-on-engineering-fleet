# Proposal: run5250Session — Virtual 5250 Terminal Session Execution

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-05
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

Agentic IBM i platforms need to execute interactive 5250 screen flows — running CL programs that display Rich Display Files (RDF), reading screen output, and responding to prompts. IBMiMCP currently has no 5250 terminal capability at all. This is a documented competitive gap: CoderFlow (a direct competitor to IBMiMCP) specifically lists "executing and validating 5250 green screens" and "interacting with Rich Display Files" as built-in skills. IBM i developers who try to automate legacy interactive programs hit a wall with IBMiMCP and turn to alternatives.

## Evidence

- [Profound Logic, 2026] "Generic agentic platforms lack AI-first tooling specifically built for IBM i such as compiling RPG, COBOL, and CL, or **running 5250 screen flows**." (emphasis added)
- [Profound Logic / CoderFlow product page, 2026] CoderFlow lists as built-in capabilities: "executing and validating 5250 green screens; interacting with Rich Display Files; querying database schemas; starting and stopping services."
- [IBM i community, general] Interactive programs (those using DDS display files / DSPF) cannot be called via SQL or standard CL `CALL`; they require a terminal session to respond to screen prompts.
- IBMiMCP tool inventory: zero files in any `terminal/` or `5250/` category. The existing `runCommand` tool submits CL commands but cannot handle interactive display-file programs or read screen output.

## Proposed change

**Type:** new tool (new category)
**Name / identifier:** `run5250Session`
**New category directory:** `src/tools/terminal/`

A tool that opens a virtual 5250 terminal session via JT400's `tn5250j` or `AS400ToolboxJavaProgram` APIs, sends a sequence of keystrokes/commands, and returns the final screen contents as structured text.

**Parameters:**
- `commands` (array of string, required) — ordered list of commands or keystrokes to send (e.g. `["CALL MYLIB/CUSTMENU", "[ENTER]", "1", "[ENTER]"]`)
- `library` (string, optional) — initial library list entry
- `maxScreens` (number, optional, default 10) — safety cap on how many screen transitions to allow per call
- `timeoutMs` (number, optional, default 5000) — per-screen wait timeout

**Example use:**
> "Run the customer inquiry menu in CUSTLIB, select option 2, and tell me what the screen shows."
> → tool call: `run5250Session(commands=["CALL CUSTLIB/CUSTMENU", "[ENTER]", "2", "[ENTER]"], library="CUSTLIB")`
> → returns: array of screen snapshots (24×80 text grid per screen)

**Response shape:**
```json
{
  "screensTraversed": 3,
  "finalScreen": {
    "rows": ["CUSTOMER INQUIRY...", "..."],
    "cursorRow": 5,
    "cursorCol": 20,
    "hasError": false
  },
  "allScreens": [...]
}
```

## Why this project is the right place for this

IBMiMCP's JDBC/JT400 stack already connects to IBM i via AS400 credentials. JT400 ships a full programmatic 5250 terminal API (`com.ibm.as400.access.AS400TextField`, `ProgramCall`, `CommandCall` with display-file support). No new dependencies required — just a new tool category using existing JT400 capabilities.

## Implementation notes

- JT400 `AS400ToolboxJavaProgram` can drive terminal sessions programmatically
- Use `CommandCall` with `*INTERACT` job type or JT400's `tn5250j` API for full screen navigation
- Existing IBMiMCP `JDBCService` already manages the AS400 connection object — re-use the same credentials
- New files: `src/tools/terminal/run5250Session.ts`, `src/tools/terminal/index.ts`
- Screen output should be sanitized before return (remove EBCDIC control characters)
- **Safety**: enforce `maxScreens` hard cap; never auto-respond to `[SYSREQ]` or `[ATTN]` keys

## Effort estimate

**High** — ~300 lines; new category; requires understanding JT400 5250 API; significant testing against pub400.com needed.

## Risk / caveats

- Interactive 5250 sessions consume a licensed user connection on IBM i; each call opens/closes a connection.
- pub400.com (test system) may have restrictions on running interactive programs in batch/headless mode.
- Must not auto-answer inquiry messages (`MSGW`) — if the session enters MSGW state, the tool should return the screen contents and let the agent decide how to respond rather than automatically replying.
- Screen output is 5250-protocol-level; EBCDIC → Unicode conversion must be handled (JT400 does this automatically via CCSID mappings).
