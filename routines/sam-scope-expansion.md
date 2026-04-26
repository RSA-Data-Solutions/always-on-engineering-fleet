# Sam-bot scope expansion for max-bug-finding mode

The original Routine 5 spec capped Sam at 5 files / 100 lines per fix
to be conservative. With max-bug-finding mode generating 10-15 issues
per day, Sam needs to handle more breadth without losing the safety
properties.

This is a SURGICAL update to Routine 5's STEP 4 only. Replace the
"Hard scope budget" block in your existing Routine 5 prompt with the
version below. Everything else stays.

## Replacement block — STEP 4 hard scope budget

```
Hard scope budget for autonomous fixes (UPDATED for max-bug mode):

Tier 1 — auto-merge eligible (severity/P3 only):
    - Maximum 2 files modified
    - Maximum 30 lines changed
    - Test fix only (no production code change)
    - Auto-merge label `safe-auto-merge` may be added by Sam, in which
      case the PR auto-merges if CI passes (no human gate)

Tier 2 — human review required (severity/P1, P2):
    - Maximum 5 files modified
    - Maximum 100 lines changed
    - Production code may be changed
    - PR opens with `awaiting-human-review`, human merges

Tier 3 — extended scope (severity/P0 only):
    - Maximum 10 files modified
    - Maximum 250 lines changed
    - Production code + minor migration may be changed
    - PR opens with `awaiting-human-review`, `extended-scope`
    - Sam includes a "Confidence" section in the PR body:
        - Confidence: HIGH — root cause identified, fix verified locally
        - Confidence: MED  — fix passes test but root cause uncertain
        - Confidence: LOW  — minimal fix, broader audit recommended
      Human reads confidence before merging.

Forbidden paths (ALL tiers — never edit without explicit label
`auth-touch-allowed` or `infra-allowed`):
    * .github/workflows/ — CI/CD pipelines
    * Auth, secrets, crypto code (orchestrator/app/routers/auth.py,
      services/auth.py, anything matching */auth*, */secret*, */crypto*)
    * Database migration files (alembic/versions/*)
    * Anything under contexts/, agents/, or SKILL.md in fleet repo
    * orchestrator/app/config.py settings.py (env var defaults)
    * Production .env.* files

Auto-merge gating (Tier 1 only):
Sam may apply the `safe-auto-merge` label only if ALL of:
    1. Severity/P3 (cosmetic, P3 doesn't trigger Sam normally — only
       reaches him via human-elevation rare path)
    2. Touches only test files (qa/, tests/, *_test.py, test_*.py)
    3. No new dependencies added
    4. No environment variables added or changed
    5. CI fully green on the PR's HEAD commit
    6. Diff has zero TODO, FIXME, XXX, or HACK comments

If Tier 3 budget hit, Sam STOPS at the budget threshold, pushes a WIP
branch with diagnosis only, comments on the issue with the partial
analysis, adds `needs-human-review` and `wip-fix-pushed` labels, and
removes `needs-fix`. Same graceful-bow-out as before.
```

## Why these changes are safe

1. **Tier 1 auto-merge only fires on P3 test-only fixes.** P3 doesn't
   normally trigger Sam (only P0/P1 fire qa-bot-fix-trigger.yml), so
   this path is rarely taken — it's there for when a human elevates
   a P3 to "let the bot self-merge a small test cleanup."

2. **Tier 3 P0 expansion has the Confidence section as a forcing
   function.** Even though humans must merge, the LOW/MED/HIGH
   confidence indicator means "treat this as a hand-grenade."
   Reviewers know not to merge LOW without their own diagnosis.

3. **Forbidden paths are unchanged.** Auth, CI, migrations, config —
   Sam still cannot touch these without an explicit human-applied
   label. No exfil paths, no privilege escalation paths.

4. **The wip-fix-pushed label is new.** Distinguishes "Sam tried, ran
   out of scope, here's what I learned" from "Sam never started."
   Helps human triage prioritise — these have a head start.

## Update to Sam-bot's PR body template

In Routine 5's STEP 5, modify the PR body template to add a
Confidence section for Tier 3 fixes:

```
Open PR via the GitHub connector:
    POST /repos/{qa_issue_repo}/pulls
    title: <commit subject>
    head: {branch}
    base: main
    body: |
      Fixes #{qa_issue_number}

      ## Confidence: <HIGH|MED|LOW>
      <One paragraph explaining why this confidence level. Required
      for severity/P0 fixes, optional for P1/P2.>

      ## Root cause
      ...
      [rest of template unchanged]
```

## Cap math sanity check

```
Per bug found by Routines A/B/C/E:
    1 routine run (already counted in scheduled 5/day)
    + 1 R5 Sam-bot fix (autofix)
    + 1 R4 retest on merge
    = 2 cap runs consumed per fixed bug

Routines budget after fixed schedule:
    15/day cap - 5 scheduled = 10/day for autofix loops
    10 / 2 per bug = 5 bugs autofixed per day on Routines path

Plus: bugs Lynn finds in homelab path also flow through R5+R4:
    Homelab finds ~3-5/day during stable periods, 10-20/day during regression
    These also consume 2 cap runs each

Practical ceiling: ~5-6 autofixes per day from any source combined.
Beyond that, fixes queue overnight.

If you regularly hit the queue, two options:
    a) Enable metered overage (best for bursty regression days)
    b) Upgrade to Team plan (25/day cap, removes the bottleneck)
```

## Anti-pattern to watch for

If Sam-bot is filing too many `false-fix` reopens, scope budget is
too aggressive. Symptoms:
    - >20% of Sam's fixes get `false-fix` label after R4 retest
    - Same issue cycles fix → reopen → fix → reopen

If you see this, tighten Tier 3 budget back to 5 files / 150 lines and
require Confidence: HIGH for severity/P0 PRs.
