# Proposal: validateDeploymentReadiness — CI/CD Deployment Readiness Validator

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-05-04
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i shops adopting AI coding tools (IBM Bob, Claude, watsonx) can generate large volumes of RPG and CL code changes in minutes, but most lack the CI/CD pipeline infrastructure to safely validate and deploy those changes. An IT Jungle article published today (2026-05-04, "From Migration To Maturity: The Cloud Reality For IBM i Shops") calls out that "without a real pipeline, AI-generated code flows straight from the developer's screen to production" and that "only automated pipelines can handle the load." A complementary press release from Eradani (circulating this week) frames their DevOps product specifically as filling "the gap AI coding tools leave behind on IBM i." The gap affects iNova users directly — AI coding sessions in the IDE produce compiled objects, and there is currently no single tool to check whether all changed objects compiled cleanly before release.

## Evidence

- IT Jungle (2026-05-04): "From Migration To Maturity: The Cloud Reality For IBM i Shops" — AI tools generating thousands of lines with no pipeline to gate deployment.
- Eradani DevOps press release (circulating May 2026): product positioned as filling "the gap AI coding tools leave behind on IBM i" — direct signal that this is an unmet need.
- IBMiMCP has individual compile tools (`compileRPGLE`, `compileCLLE`, `getCompilationErrors`) but no aggregated readiness gate — confirmed by source scan today.
- iNova Issues #4, #6: IBMiMCP deployment gate checked tool count but not individual object compile health — showing the platform already cares about readiness gates.

## Proposed change

**Type:** new tool
**Name / identifier:** `validateDeploymentReadiness`

Given a library (and optionally a list of object names), check whether all objects compiled successfully and are up to date, returning a go/no-go verdict with per-object detail. Designed to be called as a pre-deploy gate step by an AI agent or CI pipeline.

**Parameters:**
- `library` (string, required) — IBM i library to inspect (e.g. `MYLIB`)
- `objects` (string[], optional) — limit to these object names; if omitted, checks all `*PGM` and `*SRVPGM` objects in the library
- `maxAgeDays` (number, optional, default: 1) — flag objects whose last compile date is older than this many days relative to their source member's last-changed date
- `includeMessages` (boolean, optional, default: true) — return compile messages (errors/warnings) for failed objects

**Example use:**
> "Before we deploy MYLIB, check that everything compiled clean."
> → calls `validateDeploymentReadiness({ library: "MYLIB" })` → returns `{ ready: false, failed_objects: ["MYRPGPGM"], warnings: ["MYUTIL compiled 3 days ago, source changed today"] }`

**Return fields:**
- `ready`: boolean — true only if all checked objects have clean compile status and are not stale relative to source
- `library`: string
- `checked_count`: number
- `failed_objects`: `{ name, type, last_compiled, error_messages[] }[]`
- `stale_objects`: `{ name, type, source_changed, last_compiled }[]`
- `clean_objects`: string[] (names only)
- `summary`: string — one-line human-readable verdict

## Why this project is the right place for this

IBMiMCP already owns the compile toolchain; a readiness gate aggregating across that toolchain belongs here as the pre-deploy safety net for AI-assisted development workflows.

## Implementation notes

- Use `QSYS2.PROGRAM_INFO` view (or `QSYS2.OBJECT_STATISTICS`) to get last compile timestamp and source file/member info per object
- Cross-reference with `QSYS2.SYSMEMBERSTAT` for source last-changed date (already used by the recently-built `listFileMemberStats` tool)
- Stale check: if `LAST_SOURCE_CHANGE_TIMESTAMP > PROGRAM_CREATE_TIMESTAMP`, mark as stale
- Compile error check: call `getCompilationErrors` logic per failed object if `includeMessages: true`
- Lives in `src/tools/compile/validateDeploymentReadiness.ts`

## Effort estimate

**Medium** — ~150–180 lines; 2–3 QSYS2 queries joined across objects, source members, and compile status; reuses logic from `listFileMemberStats` and `getCompilationErrors`.

## Risk / caveats

- `QSYS2.PROGRAM_INFO` may not be available on V7R3 and earlier — document V7R4+ requirement.
- Libraries with thousands of objects could be slow; recommend filtering with the `objects` parameter for large libraries.
- Compile timestamps are only as fresh as the last full compile; incremental compile flows may show false-stale results if source timestamps update without a recompile.
