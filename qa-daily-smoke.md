# Daily QA Smoke Test Suite — RSA-907

## Coverage

18 smoke tests covering core flows:

### Authentication & Session (4)
- Login: Valid credentials, password correct
- Logout: Session cleanup, redirect
- Session: Token validity check
- Invalid Credentials: Rejection, error message

### UI Navigation & Core Flows (6)
- Dashboard: Load, basic render, no console errors
- Navigation: Main menu, breadcrumbs, page routing
- Forms: Submit, validation, error handling
- Search: Query handling, result display
- Profile: Load user data, edit, save
- 404/500 Error Pages: Error handling, recovery

### Data & Performance (5)
- Pagination: Navigation, page size changes, bounds
- Images: Load, display, no broken references
- Bulk Actions: Multi-select, batch operations
- Load Time: P95 under 3s, Core Web Vitals
- Console Errors: Zero uncaught exceptions

### Client Support (3)
- Mobile: Responsive, touch interactions
- Dark Mode: Toggle, persistence
- Export: Format generation, download

---

## Execution

**Routine:** Daily QA Smoke (cron: `0 8 * * *` UTC = 02:00 Central)

**Agent:** Lynn (QA Engineer) via `agents/lynn.md`

**Test Suite:** `scripts/smoke_tests.py` in iNova repo

**Output:**
- `fleet-workspace/qa-daily/YYYY-MM-DD-report.json` — results + failures
- Failure comment posted to Paperclip issue system
- Alert triggered on 2+ failures

**Retention:** 30 days rolling

---

## Monitoring

**Dashboard:** `fleet-workspace/qa-daily/index.md` (updated each run)

**Metrics Tracked:**
- Pass rate (% tests passing)
- Mean test duration
- Failure classification (code_bug vs env_problem vs flaky)
- Trend: 7-day rolling avg pass rate

**Alert Triggers:**
- 2+ failures in single run
- Same test fails 3 consecutive days
- Pass rate drops >10% day-over-day

---

## Integration

Automated failures file issues in Paperclip with labels:
- `qa-bot` — auto-filed by QA
- `severity/P1` or `severity/P2` per impact
- `needs-fix` — Sam can pick up

CTO reviews daily report and approves/defers fixes.

---

## Known environment blocker

`qa-smoke-daily` has been blocked (`env_problem`, 0/18 tests) since 2026-05-20 because the
always-on cloud session cannot reach the `RSA-Data-Solutions/iNova` repo. See
[Issue #11](https://github.com/RSA-Data-Solutions/always-on-engineering-fleet/issues/11) and
the decision record at `fleet-workspace/issue11-inova-access-decision.md` for root cause and
the required unblock action (environment config change by a human operator — not fixable in
this repo). Do not file duplicate incidents for this same root cause; append a heartbeat line
and reference Issue #11 instead.
