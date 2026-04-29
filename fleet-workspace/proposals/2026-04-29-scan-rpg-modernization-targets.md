# Proposal: scanRPGModernizationTargets — Source Member Modernization Triage Scanner

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-29
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM Project Bob (GA March 24, 2026) helps developers modernize RPG code — but only at the
code snippet level in VS Code. It has no way to survey a library or source file and answer
"how much of our codebase needs modernization, and where should we start?" Developers
described this gap explicitly: Bob "won't map your application's procedural flow, generate
entity-relationship diagrams, or reveal system dependencies." Before teams can use Bob
effectively, they need a bulk triage: which source members contain fixed-format RPG, which
use deprecated op-codes, and which are OPM vs. ILE programs. Today this requires manual
review or expensive third-party tooling.

## Evidence

- [IT Jungle, March 2026](https://www.itjungle.com/2026/03/02/ibm-gets-bob-1-0-off-the-ground/)
  — "Project Bob does not function as an IBM i application modernization or system analysis tool.
  It works at the code snippet level."
- [Freschesolutions — Where Project Bob Fits](https://freschesolutions.com/resource/where-project-bob-fits-in-your-ibm-i-modernization-strategy/)
  — Bob's "iMode" feature (native IBM i source navigation) has not yet shipped; no system-wide
  triage capability exists in the GA release.
- [TheRPGBlend Substack](https://therpgblend.substack.com/p/project-bob-vs-code-and-the-future)
  — Community discussion: "Managers need to prepare for the gap between Bob's code-level help
  and the application-wide inventory they need to plan a modernization project."
- [In-Com RPG Modernization 2026](https://www.in-com.com/blog/ibm-i-rpg-modernization-solutions-2026-tools-vs-service-providers-comparison/)
  — Third-party providers still charge significant fees for modernization inventory/assessment
  work that is fundamentally a source scan.

## Proposed change

**Type:** new tool
**Name / identifier:** `scanRPGModernizationTargets`

Scan source members in a given source file (or all RPG/RPGLE members in a library) and
classify them by modernization category: OPM vs. ILE, fixed-format vs. free-format, presence
of deprecated patterns (CALL vs CALLP, H/F/D/C specs, `/COPY` vs `/INCLUDE`), and estimated
modernization effort (line count + pattern density). Returns a structured summary suitable
for project planning.

**Parameters:**
- `library` (string, required): library containing the source file(s) to scan
- `sourceFile` (string, optional): specific source physical file (e.g. `QRPGLESRC`); defaults
  to scanning all RPGLE-type members across the library
- `maxMembers` (number, optional, default 200): scan cap to avoid runaway runtime

**Example use:**
> "Give me a modernization inventory of library ACCTPAY"
> → calls `scanRPGModernizationTargets({ library: "ACCTPAY" })`
> → returns: member count by category, top 10 highest-effort modernization targets, summary
>   stats (% fixed-format, % OPM, % using deprecated CALL op-code)

## Why this project is the right place for this

IBMiMCP already has `searchSourceMembers` and `listSourceMembers`; this tool adds the
pattern-classification layer that turns source text into actionable modernization intelligence,
directly complementing IBM Project Bob's workflow inside inovaide.com workspaces.

## Implementation notes

- Use `listSourceMembers` + `getSourceMember` in a loop (respect `maxMembers` cap)
- Pattern detection via text analysis of member content:
  - Fixed-format: lines where col 6 = `H`, `F`, `D`, `C`, `O`, `P` (not in a `/FREE` block)
  - OPM indicator: member type `RPG` (not `RPGLE`) or `PGM` attribute without ILE
  - Deprecated `CALL` (vs `CALLP`): regex `^\s+C\s+.*\bCALL\b` in fixed-format C-specs
  - `/COPY` usage: older include mechanism vs `/INCLUDE`
- Line count from `QSYS2.SYSMEMBERSTAT` (`DATA_SIZE` / estimated line length) for effort scoring
- Return structured JSON with per-member classification + aggregated summary

## Effort estimate

**Medium** — ~180–220 lines; member iteration loop, regex pattern detection, aggregation.
Reuses existing `searchSourceMembers` and `listSourceMembers` infrastructure.

## Risk / caveats

- Pattern detection is heuristic — won't catch all fixed-format patterns (embedded SQL,
  `/FREE...ENDFREE` blocks, etc.); good enough for triage, not for guaranteed accuracy
- Scanning large libraries (thousands of members) may be slow; `maxMembers` cap mitigates this
- Does not execute or compile code — purely static text analysis, so safe on any environment
