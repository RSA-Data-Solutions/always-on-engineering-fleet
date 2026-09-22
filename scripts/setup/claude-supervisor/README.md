# Build plan — Claude Supervisor

This builds the "Claude Supervisor role" proposed in
[`paperclip-hermes-always-on-engineering-fleet-migration-plan.md`](../../../paperclip-hermes-always-on-engineering-fleet-migration-plan.md#claude-supervisor-role).
That document explains *why*; this one is the concrete, runnable *how*.

**Scope of this pass:** Claude Supervisor only. Installing Paperclip itself
and onboarding Hermes as real Paperclip agents (Ram as `hermes_gateway`,
Aaron/Dhira/Lynn/Sam as `hermes_local`) is a prerequisite covered in
[`../paperclip-hermes/README.md`](../paperclip-hermes/README.md) — do that
first. `OPERATIONS.md` describes that org chart as already live; as of
2026-09-21 it wasn't (Paperclip was never installed on the host), so nothing
in this directory can do anything useful until that's done for real.

**I cannot run any of this.** This was written from a Mac Claude Code
session with no access to the Ubuntu host (`sashi-llm`) that actually runs
Paperclip/Hermes. Every script here is meant to be copied over and executed
there, by you, after the manual steps below.

---

## What's verified vs. assumed

Be honest with yourself about this before running anything. Status as of
2026-09-21, after Paperclip turned out to not actually be installed (see
`../paperclip-hermes/README.md`) — this downgraded a lot of what the
previous version of this section called "verified," since it had been
sourced from `OPERATIONS.md`'s claims rather than the real project.

**Verified** (confirmed directly against
[`paperclipai/paperclip`](https://github.com/paperclipai/paperclip)'s
`doc/CLI.md`, the real upstream project — 81k★, MIT, not a guess):
- `paperclipai issue list --company-id <id> --status in_review --api-key
  <key> --json` — real flags, confirmed in the docs.
- `paperclipai approval create --company-id <id> --type <type> --payload
  '<json>' [--issue-ids <id>] --api-key <key> --json` — real flags. Identity
  comes from the API key, not a `--requested-by-agent-id` flag (that was a
  guess from `OPERATIONS.md`'s illustrative example, which turns out not to
  match the real CLI syntax at all — treat every command example in
  `OPERATIONS.md` with the same suspicion until independently re-checked).
- `paperclipai token agent create --company-id <id> --agent <agent-id> --name
  <name>` mints a scoped agent API key — this is how claude-supervisor's own
  `PAPERCLIP_API_KEY` gets created.
- Paperclip is a real Node.js server + React UI with an embedded Postgres
  (no external DB setup), installs via `curl -fsSLO
  https://paperclip.ing/install.sh && bash install.sh`, and runs as a
  systemd **user** unit on Linux — `OPERATIONS.md`'s port (3100) and
  service-shape claims were directionally right even though the install
  itself hadn't happened.
- Paperclip ships native `hermes_local` / `hermes_gateway` adapters
  (confirmed in `doc/HERMES_GATEWAY_ONBOARDING.md`) for exactly the Hermes
  setup already on this host, and a native `claude_local` adapter (harness
  `claude`, credential `ANTHROPIC_API_KEY`) — see "Alternative approach"
  below, this is no longer speculative.

**Still assumed / not independently confirmed:**
- The company id below (`0c265070-3974-497a-99ee-cf942ffe139d`) —
  `OPERATIONS.md`'s claim, unverifiable until Paperclip is actually
  installed and `paperclipai company list` can be run for real.
- Whether Paperclip issues carry any explicit link to a repo/commit —
  `find_repo_context()` falls back to a heuristic `git log --grep=<issue-key>`
  across the three known local repos. A miss is expected and handled (the
  review says so and lowers confidence), not a bug.
- The exact JSON field names on an issue object (`key`/`id`/`updatedAt`/
  `comments` as `claude_supervisor.py` expects) — `doc/CLI.md` documents the
  command surface, not the response schema. Run `paperclipai issue list
  --company-id <id> --json | head -c 2000` once real data exists and adjust
  if the shape differs.
- Whether `--type` on `approval create` is a free-form string or a fixed
  enum — only `hire_agent` appears as an example. `paperclipai openapi`
  dumps the real schema; check it before trusting `claude_review` as a type.
- **The `claude` CLI flags used in `call_claude()`** (`-p`, `--model`,
  `--disallowedTools`, `--max-turns`, `--output-format`) and the exact
  headless-auth command (`claude setup-token`) — unrelated to Paperclip,
  still unverified against the real host. Run `claude --help` there, and
  definitely run `verify.sh`'s tool-lockdown check before trusting it.

## Claude via CLI, not API key

This build calls Claude through the `claude` (Claude Code) CLI in one-shot
print mode (`claude -p "..."`) rather than the Anthropic API/SDK. Trade-offs,
so this is a deliberate choice rather than a default worth forgetting about:

- **Cost**: usage draws on a Claude subscription (Pro/Max) rather than
  metered per-token API billing — the right call for a homelab budget, at
  the cost of sharing that plan's usage limits with your interactive coding
  sessions.
- **Safety — this is the one that matters.** The Anthropic API only ever
  returns text; there was no tool-access question. `claude` is a full
  agentic coding tool with shell/file-write access *by default*. Every call
  in `claude_supervisor.py` passes `--disallowedTools` naming every built-in
  tool, `--max-turns 1`, and runs from an empty scratch directory — this is
  what makes "advisory only, no shell" still true under this design, not
  just documentation. If you ever modify `call_claude()`, keep the lockdown;
  don't treat it as boilerplate to trim. `verify.sh` includes a live check
  that asks Claude to try running `ls` and confirms it can't — run that
  after any change here, and after any `claude` CLI upgrade.
- **Auth is a one-time manual step**, same weight as provisioning an API key
  would have been: either `claude login` (interactive) or `claude
  setup-token` (built for headless/CI use — verify the exact command) as the
  `sashi` user on the host, before starting the service.

If you'd rather use the Anthropic API directly instead (isolated, text-only,
no agentic surface to lock down, but metered billing), swap `call_claude()`
back to the `anthropic` Python SDK — it's a single self-contained function.

---

## Manual setup (you do this, not the scripts — needs board access)

1. **Create a Paperclip agent identity for claude-supervisor**, following
   the pattern in `OPERATIONS.md`'s "Adding a new agent" section:
   - `reportsTo`: Ram's agent id (`093a44a5-da1d-421a-9708-cd1f05e6d734`), or
     leave it a peer if Paperclip requires a different structure for a
     non-`hermes_local` role — verify.
   - This identity does **not** need `hermes_local`/`hermes_gateway` wiring,
     since nothing triggers its heartbeat — it's driven by the standalone
     daemon instead. If Paperclip's agent-creation flow requires an adapter
     type regardless, pick whatever is least-privileged and don't wire a
     model to it.
2. **Provision an API key scoped to claude-supervisor** with permission to
   call `issue list` (read, project-scoped) and `approval create` (write),
   but **not** `create-task`, `update-status` on other agents' issues, or
   `approval approve`/`reject`. If Paperclip's key model doesn't support
   this exact shape, use the narrowest key type available and note the gap
   — don't grant broader access to work around a missing key type without
   flagging it.
3. **Install and authenticate `claude` (Claude Code CLI) as the `sashi` user**
   on the host, if not already done — `claude login` (interactive) or
   `claude setup-token` (headless; verify the exact command). See "Claude
   via CLI, not API key" below for why this replaces an Anthropic API key.
4. Record the new agent id and the Paperclip API key — you'll put them in
   `~/.claude-supervisor/.env` on the host (step 1 of "Deploy" below).

## Deploy (on the Ubuntu host, as `sashi`)

```bash
scp -r scripts/setup/claude-supervisor sashi@sashi-llm:~/claude-supervisor-setup
ssh sashi@sashi-llm
cd ~/claude-supervisor-setup
./install.sh
# edit ~/.claude-supervisor/.env with the values from "Manual setup" above
./verify.sh
# if the dry run looks right:
systemctl --user enable --now claude-supervisor
journalctl --user -u claude-supervisor -f
```

`install.sh` is idempotent — safe to re-run after pulling an updated
`claude_supervisor.py` from this repo. It never overwrites an existing
`.env` and never starts the service on its own.

## Rollout — start read-only across all three projects at once

Because the daemon only reads issues and files advisory approval requests —
never a status change, never a repo write — there's no reason to stage it
project-by-project the way code-writing changes would be. Turn it on once
and let it watch `in_review` issues from IBMiMCP, iNova, and the fleet's own
self-improvement work simultaneously. Check `paperclipai approval list -C
0c265070-3974-497a-99ee-cf942ffe139d` after the first few review cycles and
read Claude's actual output before trusting it — the same "verify, don't
assume" standard the rest of this repo holds itself to.

## Known limitations

- **Diff matching is heuristic.** A review filed with no matching commit
  found is lower-confidence by construction (the prompt says so and asks
  Claude to reflect that). Don't treat "no match" reviews as equivalent to
  ones grounded in an actual diff.
- **Single shared Paperclip project.** All three real projects share one
  Paperclip project id, so this daemon reviews `in_review` issues across all
  of them indiscriminately — there's no Paperclip-side way to scope it to
  just one project without narrower filtering than what's built here (issue
  title/label matching would need to be added if you want that).
- **Poll-based, not event-driven.** Default 300s interval. Paperclip's own
  heartbeat is ~30s; this is deliberately slower per the cost-control
  guidance in the migration plan — don't tighten it without a reason.
- **The exact `paperclipai` JSON field names are unverified** (see above).
  If issues break immediately after deploy, this is the first thing to
  check.

## Alternative approach (not built here, worth investigating)

Paperclip ships a native `claude_local` adapter — it runs the `claude` CLI
directly as a per-heartbeat child process, the same way `hermes_local` runs
`hermes`. If that adapter's config supports restricting tool access (check
with `paperclipai adapter config-schema claude_local` once Paperclip is
installed), Claude Supervisor should become a real Paperclip agent using
that adapter instead of the standalone daemon in this directory — full reuse
of Paperclip's own heartbeat/dispatch/reporting mechanism, no separate poll
loop to maintain.

**Don't switch to it until that question is answered.** The native adapter's
documented credential is `ANTHROPIC_API_KEY` (metered billing, not the
`claude` CLI's subscription auth this build uses), and nothing in the docs
confirms it exposes a tool-restriction knob — if it doesn't, using it would
silently hand Claude Supervisor full Claude Code tool access (Bash, Read,
Write, Edit) by default, which defeats the entire "advisory only" design.
The standalone daemon's explicit `--disallowedTools` lockdown is a known
quantity; the native adapter's tool-access behavior currently isn't.
