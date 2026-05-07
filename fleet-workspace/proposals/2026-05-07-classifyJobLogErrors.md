# Proposal: classifyJobLogErrors — Structured Job Log Error Classification

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-07
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i developers using AI tools to debug compilation failures and runtime errors get back
an unstructured wall of text from `getJobLog`. They must mentally parse dozens of messages
to find the CPF/MCH/SQL error codes that actually matter — a task made harder when errors
chain (one root CPF causes five follow-on messages). The IT Jungle reported in March 2026
that the IBM i VS Code community specifically built the "Job Log Detective" extension to
solve this exact structured-analysis gap, confirming the pain is real and community-wide.
`analyzeJobAbendAndCrash` addresses post-mortem analysis of crashed jobs; no tool
classifies errors across *any* job log in a structured, grouped format.

## Evidence

- [IT Jungle, 2026-03-09] "Guru: IBM i Job Log Detective Brings Structure To Job Log
  Analysis In VS Code" — confirms that raw job log parsing is painful enough that a
  dedicated VS Code extension was published in 2026 to address it; the article describes
  the core need as "grouping errors by message ID prefix and severity so developers can
  find root causes quickly."
- [blog.richardschoen.net, 2026-02] "My #%## SQL RPG Program Won't Compile" — documents
  a developer's frustration tracing SQL compilation errors through a raw job log; line width
  issues in SQLRPGLE surface as deeply buried CPF5812/RNF messages that a structured view
  would surface immediately.
- [IBM/ibmi-mcp-server GitHub #119, 2026-03] Feature request for MCP elicitation cites
  "when queries return ambiguous large results forcing the LLM to guess" as the primary
  pain — structured job log output directly reduces this ambiguity.
- Pattern also matches issue #52 (unnamed temporary storage TypeError) which arose from
  inadequate structured feedback about what the job was doing.

## Proposed change

**Type:** new tool
**Name / identifier:** `classifyJobLogErrors`

Takes a job identifier (or defaults to current job), reads the job log via
`QSYS2.JOBLOG_INFO`, and returns a structured classification: errors grouped by message
ID prefix, a severity histogram, root-cause candidates (highest-severity non-diagnostic
message), and a plain-English summary line per error group. Unlike `getJobLog` (returns all
messages verbatim) and `analyzeJobAbendAndCrash` (post-mortem of crashed jobs only), this
works on any job and produces structured, digestible output.

**Parameters:**
- `jobId` (string, optional) — job in NUMBER/USER/NAME format; defaults to current job
- `minSeverity` (number, optional, default 20) — skip informational noise; 20 = warnings+
- `includeSecondLevel` (boolean, optional, default true) — include second-level message text
- `maxErrorGroups` (number, optional, default 20) — cap on distinct message ID groups returned

**Example use:**
> "What went wrong in the last compile job for user MSASHI?"
→ `classifyJobLogErrors({ jobId: "123456/MSASHI/QPADEV0001", minSeverity: 20 })`

**Output:**
```json
{
  "success": true,
  "jobId": "123456/MSASHI/QPADEV0001",
  "totalMessages": 47,
  "errorCount": 8,
  "warningCount": 3,
  "rootCauseCandidates": [
    {
      "messageId": "RNF0257",
      "severity": 40,
      "count": 12,
      "category": "RPG",
      "firstOccurrence": "2026-05-07T10:14:22",
      "sampleText": "Syntax error or keyword not allowed at this position",
      "fromProgram": "QRNFLT00"
    }
  ],
  "errorGroups": [
    {
      "prefix": "RNF",
      "category": "RPG compiler",
      "count": 14,
      "highestSeverity": 40,
      "messageIds": ["RNF0257", "RNF3218"]
    },
    {
      "prefix": "CPF",
      "category": "IBM i system",
      "count": 2,
      "highestSeverity": 30,
      "messageIds": ["CPF5812"]
    }
  ],
  "summary": "14 RPG compiler errors (root: RNF0257 — syntax error, 12 occurrences). 2 CPF system messages. Likely cause: CCSID encoding or line width issue in SQLRPGLE source."
}
```

## Why this project is the right place for this

IBMiMCP owns the job log interface (`getJobLog`); adding classification on top of the same
`QSYS2.JOBLOG_INFO` foundation is a natural extension that keeps all IBM i diagnostic
capability in one server.

## Implementation notes

- Query `QSYS2.JOBLOG_INFO` with `WHERE CAST(SEVERITY AS INTEGER) >= minSeverity`
- Group by `LEFT(MESSAGE_ID, 3)` for prefix buckets (RNF=RPG, CPF=system, SQL=SQL, MCH=machine)
- Identify root-cause candidate as the first message with severity >= 30 that isn't a
  "diagnostic" type (MESSAGE_TYPE != 'D')
- Category map: `RNF`→"RPG compiler", `SQL`→"SQL precompiler", `MCH`→"machine check",
  `CPF`→"IBM i system", `CPC`→"completion", `CPD`→"diagnostic", else→"other"
- Summary line: generated from top error group; no LLM call needed — string template
- Reuses existing SQL infrastructure; no new IBM i API calls needed

## Effort estimate

**Low** — ~100 lines: SQL query (~20 lines, reuses JOBLOG_INFO pattern from getJobLog),
grouping/classification logic (~50 lines), output schema (~20 lines), error handling (~10 lines).

## Risk / caveats

- Jobs that have already ended: `JOBLOG_INFO` supports ended jobs if their job log is still
  on the system; no special handling needed
- Large job logs: `minSeverity` default of 20 will filter most noise; add `FETCH FIRST 500`
  guard before grouping
- `QSYS2.JOBLOG_INFO` requires the calling user to have authority to the target job's log;
  document this in tool description
