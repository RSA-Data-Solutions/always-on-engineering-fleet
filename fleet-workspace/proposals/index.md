# IBMiMCP Research Proposals Index

## Past Proposals

| Date | Title | Status | CTO Outcome |
|------|-------|--------|------------|
| 2026-04-19 | captureCallStack — Advanced Call Stack Extraction | Built & Released | Shipped commit e1733bf |
| 2026-04-19 | generateAuditComplianceReport — Compliance Report Generator | Deferred | Scope too large; re-propose scoped-down version |
| 2026-04-19 | analyzeIFSStorage — IFS Storage Analyzer | Built & Released | Shipped commit 918abde |
| 2026-04-19 | inspectDataQueue — Data Queue Inspector | Built & Released | Shipped commit 918abde |

## Today's Proposals (2026-04-20)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-20 | analyzeModuleDependencies — Module/Service Program Dependency Graph | High | Deferred | QBNLPGMI API not accessible via JDBC; partial overlap with getObjectDependencyChain |
| 2026-04-20 | captureRuntimePerformanceProfile — Real-Time Performance Profiling | High | Approved | Real gap; analyzeJobPerformance is a stub; implement as before/after ACTIVE_JOB_INFO delta |

## Today's Proposals (2026-04-21)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-21 | detectAndAnalyzeLockContention — Real-Time Lock Contention Detection & Analysis | High | Rejected | Near-duplicate of analyzeLockContention (built 2026-04-06); extend existing tool if sampling needed |
| 2026-04-21 | analyzeJobAbendAndCrash — Job Crash Root-Cause Analysis & Abend Diagnostics | High | Approved | Real gap; IBM Fault Analyzer is Java-only; implement via JOBLOG_INFO + STACK_INFO + MCH/CPF/SQL pattern matching |

## Today's Proposals (2026-04-22)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-22 | detectSQLCursorLeaks — SQL Cursor & Handle Leak Detection | High | Deferred | QSYS2.SQL_CURSOR_INFO not confirmed on V7R5; DUMP_SQL_CURSORS writes to spoolfile, not result set — implementation path unverified |
| 2026-04-22 | forecastDatabaseFileGrowth — Database File Size Growth Forecasting & Capacity Analysis | High | Approved | Clear gap vs analyzeLibraryStorage; QSYS2.LIBRARY_INFO + ASP_INFO confirmed; build single-snapshot mode only, ~150 lines |

## Today's Proposals (2026-04-23)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-23 | getMemoryPoolAnalysis — Real-Time Memory Pool Diagnostics | High | Approved | Use TABLE(QSYS2.MEMORY_POOL()) X; corrected from wrong view names; single-snapshot, ~150 lines |
| 2026-04-23 | analyzeSplooledFileLifecycle — Spooled File User/Job Attribution & Cleanup Forecast | High | Approved | Scoped to user/job attribution + forecast only; queue analytics already in analyzeSpooledFileHealth |

## Today's Proposals (2026-04-24)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-24 | auditIFSAuthority — IFS Object Authority Auditor | High | Approved | QSYS2.IFS_OBJECT_PRIVILEGES; security/ category; ~130 lines |
| 2026-04-24 | analyzePreStartJobs — Prestart Job Pool Health & Tuning Advisor | High | Approved | PRESTART_JOB_INFO + optional PRESTART_JOB_STATISTICS; operator/ category; ~150 lines |

## Today's Proposals (2026-04-25)

| Date | Title | Priority | Status | CTO Outcome |
|------|-------|----------|--------|-------------|
| 2026-04-25 | listFileMemberStats — Physical File Member Statistics & Reorganization Advisor | High | Approved | QSYS2.SYSMEMBERSTAT; source/ category; ~110 lines |
| 2026-04-25 | inspectUncommittedTransactions — Uncommitted Database Transaction Inspector | High | Approved | QSYS2.DB_TRANSACTION_INFO + DB_TRANSACTION_OBJECT_INFO; operator/ category; ~140 lines |
