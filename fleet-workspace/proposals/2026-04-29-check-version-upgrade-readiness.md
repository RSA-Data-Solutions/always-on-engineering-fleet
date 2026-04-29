# Proposal: checkVersionUpgradeReadiness — IBM i OS Version Upgrade Pre-flight Scanner

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-29
**Project:** IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

IBM i 7.4 reaches end-of-marketing on April 30, 2026 (tomorrow), and end-of-standard-support on
September 30, 2026. Shops on 7.4 are urgently planning upgrades to 7.5 or 7.6, but IBM's own
pre-upgrade verification tool is passive — it flags missed steps but cannot query the live
system state via an AI agent. Developers and admins have no single-command way to ask "am I
ready to upgrade?" against the running system. IBM i 7.6 also imposes a Power 10 hardware
requirement, making hardware-version awareness critical before planning.

## Evidence

- [IT Jungle, Sep 2025](https://www.itjungle.com/2025/09/22/and-then-there-were-two-big-blue-withdraws-ibm-i-7-4/)
  — "IBM i 7.4 withdrawn from marketing April 30, 2026; end of standard support September 30, 2026."
- [Covenco Technical Bulletin](https://covenco.com/insights/blog/technical-bulletin-critical-update-on-ibm-i-7-4-lifecycle-planning-for-version-7-6-migration/)
  — "Enterprise upgrades often take months or years to plan… waiting until 2026 will leave businesses
  under pressure, facing rushed projects and unplanned downtime."
- [Proximity, Sep 2025](https://proximity.co.uk/blog/ibm-i-update-september-2025-support-ending-for-ibm-i-7-4/)
  — IBM i 7.6 requires Power 10 hardware; many 7.4 shops cannot go directly to 7.6 and must
  evaluate whether to upgrade to 7.5 or replace hardware.
- [IBM Release Lifecycle page](https://www.ibm.com/support/pages/release-life-cycle)
  — Db2 Web Query for i also reaches end of support December 31, 2026.

## Proposed change

**Type:** new tool
**Name / identifier:** `checkVersionUpgradeReadiness`

Query QSYS2 system tables and system values to produce a structured upgrade readiness report
for a target OS version (7.5 or 7.6). The report includes: current OS version and PTF level,
installed PTF groups vs. required baseline, hardware model and POWER level (to flag 7.6
ineligibility), and whether Db2 Web Query is installed (flagging its 2026 EOL separately).

**Parameters:**
- `targetVersion` (string, required): `"7.5"` or `"7.6"`
- `library` (string, optional): limit PTF check to a specific library list

**Example use:**
> "Check if our system is ready to upgrade to IBM i 7.5"
> → calls `checkVersionUpgradeReadiness({ targetVersion: "7.5" })`
> → returns: current version, PTF group gaps, hardware POWER level, blocking conditions, and a
>   summary recommendation (READY / NEEDS_ATTENTION / BLOCKED).

## Why this project is the right place for this

IBMiMCP already exposes `listInstalledPTFs` and `getSystemStatus`; this tool combines those
signals with version-target logic to produce an actionable upgrade decision, which is exactly
the kind of AI-agent-accessible system intelligence inovaide.com is built to deliver.

## Implementation notes

- `SELECT * FROM QSYS2.PTF_INFO WHERE PTF_STATUS <> 'APPLIED'` for PTF gap detection
- `SELECT SYSTEM_VALUE_NAME, CURRENT_NUMERIC_VALUE FROM QSYS2.SYSTEM_VALUE_INFO WHERE SYSTEM_VALUE_NAME = 'QMODEL'` for hardware model
- `SELECT * FROM QSYS2.SOFTWARE_PRODUCT_INFO WHERE PRODUCT_ID = '5770QU1'` to detect Db2 Web Query
- `SELECT OS_VERSION, OS_RELEASE FROM QSYS2.DB_TRANSACTION_INFO` — or `SYSTEM_STATUS_INFO` for
  version detection: `SELECT * FROM TABLE(QSYS2.SYSTEM_STATUS_INFO()) X`
- Map QMODEL codes to POWER generation to detect Power 10 requirement for 7.6

## Effort estimate

**Medium** — ~150–180 lines; 2–3 QSYS2 queries, result aggregation, version-target logic.

## Risk / caveats

- Hardware model mapping table must be maintained as IBM releases new POWER generations
- PTF group requirements change with each TR (Technology Refresh); may need a static lookup
  table that requires periodic updates
- 7.6 hardware requirement check is binary (Power 10 yes/no); softer hardware constraints
  (RAM, storage) cannot be detected via QSYS2 alone
