# Issue #11 Decision Record — iNova Repo Unreachable (qa-smoke-daily)

**Issue:** [RSA-Data-Solutions/always-on-engineering-fleet#11](https://github.com/RSA-Data-Solutions/always-on-engineering-fleet/issues/11) — ALERT: qa-smoke-daily blocked — iNova repo unreachable
**Decision Date:** 2026-07-04
**Decision Maker:** Ram (CTO)
**Status:** DECIDED — BLOCKED on environment configuration (human action required)

---

## Question

Can the `qa-smoke-daily` routine's inability to reach `RSA-Data-Solutions/iNova` be fixed from
inside the `always-on-engineering-fleet` repository?

## Answer

**NO.** This is not a code defect in this repository. The cloud/ephemeral session that runs
`qa-smoke-daily` only has:

1. No GitHub credentials wired into the container for `https://github.com` HTTPS clone
   (`fatal: could not read Username for 'https://github.com'`).
2. A GitHub MCP tool scope restricted to `rsa-data-solutions/always-on-engineering-fleet`.
   Any call against `RSA-Data-Solutions/iNova` returns `403 Access Denied` /
   `not configured for this session`.

Neither of these can be changed by editing files in this repo — they are properties of the
**environment configuration** for the always-on session (Claude Code on the web → Settings →
Sources, or the `GITHUB_PAT` env var supplied to the container). No amount of retrying,
re-cloning, or code changes here will restore access.

## Root Cause Classification

**Primary:** Environment/session configuration gap — `RSA-Data-Solutions/iNova` was never
added as an accessible source repo (or PAT secret) for the always-on session that hosts
`qa-smoke-daily`.

**Evidence of persistence:** 46+ consecutive daily runs (2026-05-20 → 2026-07-04) with
identical `env_problem` signature and 0/18 tests executed each day — see
`fleet-workspace/qa-daily/*-report.json` and `fleet-workspace/heartbeats/qa-smoke-daily.txt`.

## Decision

**Status:** BLOCKED (escalation to human operator required — cannot be self-resolved by any
fleet agent).

**Unblock Owner:** Human operator with access to the always-on environment configuration
(`@msasikumar`).

**Unblock Action — pick ONE:**

| Option | Action |
|--------|--------|
| **A** | Add `RSA-Data-Solutions/iNova` as a source repo in the always-on environment config (Claude Code on the web → Settings → Sources) |
| **B** | Provide a `GITHUB_PAT` env var with `Contents: read` permission for `RSA-Data-Solutions/iNova` in the environment config |

**Fleet-side follow-up once unblocked:**
1. Re-run `qa-smoke-daily` and confirm the iNova repo clones / MCP calls succeed.
2. Confirm 18/18 tests execute (pass or fail — the important thing is they *run*).
3. Append a heartbeat line to `fleet-workspace/heartbeats/qa-smoke-daily.txt` recording the
   first successful (non-`env_problem`) run.
4. Close this issue and remove the "Known environment blocker" note from
   `contexts/inova.md` once confirmed stable for 2+ consecutive days.

## What has been done in this repository (no further code action possible)

- Documented the blocker prominently in `contexts/inova.md` under "Known environment
  blocker" so future `qa-smoke-daily` runs recognize it immediately, reference this decision
  record and Issue #11, and stop re-diagnosing/re-filing duplicate incident reports.
- Added a pointer from `qa-daily-smoke.md` to this record.

## Related Documentation

- Issue: [#11](https://github.com/RSA-Data-Solutions/always-on-engineering-fleet/issues/11)
- Context: `contexts/inova.md` — "Known environment blocker" section
- Routine: `qa-daily-smoke.md`
- Evidence: `fleet-workspace/qa-daily/2026-06-21-report.json` through
  `fleet-workspace/qa-daily/2026-07-04-report.json`, `fleet-workspace/heartbeats/qa-smoke-daily.txt`

---

**Decision Recorded:** 2026-07-04
**Authority:** Ram (CTO)
**Status:** Ready for human operator action (Option A or B above)
