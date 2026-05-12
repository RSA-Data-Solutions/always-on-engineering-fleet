# IBMiMCP Fleet Summary — 2026-05-12

## Status: COMPLETE ✓

### What Was Built & Shipped

**analyzePTFCurrency Tool** (`src/tools/system/`) — Bulk PTF risk and currency scanner via `QSYS2.USER_INFO_PTFS`. Classifies HIPER, defective, temporary, and superseded PTFs with per-PTF remediation advisories. Handles systems where `PTF_HIPER` column is absent via graceful SQL fallback.

**auditUserProfiles Tool** (`src/tools/security/`) — Proactive user profile security audit via `QSYS2.USER_INFO`. Flags three risk categories across all (or filtered) profiles:
- `DEFAULT_PASSWORD` CRITICAL — never-changed passwords
- `EXCESSIVE_AUTHORITY` HIGH — *ALLOBJ/*SECADM on non-*SECOFR accounts
- `NO_PASSWORD_EXPIRY` MEDIUM — enabled profiles with no expiration interval

Both tools are read-only, require no confirmation, and return structured findings with `CHGUSRPRF`/`APYPTF` remediation commands.

**Shipped to:** GitHub (RSA-Data-Solutions/IBMiMCP)
**Commit:** bd95424
**Branch:** main

### Files Modified/Created

- `src/tools/system/analyzePTFCurrency.ts` (NEW)
- `src/tools/security/auditUserProfiles.ts` (NEW)
- `src/tools/system/index.ts` (MODIFIED — added analyzePTFCurrencyTool export)
- `src/tools/security/index.ts` (MODIFIED — added auditUserProfilesTool export)
- `src/tools/registry.ts` (MODIFIED — registered both tools; fixed pre-existing duplicate getMemoryPoolAnalysisTool entry)

### QA Results

✓ **22/22 tests passed** — no regressions
✓ Build: `tsc` exits 0, no type errors
✓ Both tools registered and visible in tool list

### Proposals

- `fleet-workspace/proposals/2026-05-12-proposal-1.md` — analyzePTFCurrency (approved + shipped)
- `fleet-workspace/proposals/2026-05-12-proposal-2.md` — auditUserProfiles (approved + shipped)

---

**Fleet Status:** Idle, awaiting next run.
