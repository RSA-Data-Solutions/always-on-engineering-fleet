# Build plan — Claude Supervisor

This builds the "Claude Supervisor role" proposed in
[`paperclip-hermes-always-on-engineering-fleet-migration-plan.md`](../../../paperclip-hermes-always-on-engineering-fleet-migration-plan.md#claude-supervisor-role).
That document explains *why*; this one is the concrete, runnable *how*.

**Scope of this pass:** Claude Supervisor only. A separate, later pass will
turn the rest of the fleet's manual setup (llama.cpp, Paperclip, Hermes, the
five existing agents — all currently hand-built per `OPERATIONS.md`, with no
setup scripts) into reproducible automation. Don't conflate the two — this
directory only stands up the new advisory layer alongside the fleet that's
already running.

**I cannot run any of this.** This was written from a Mac Claude Code
session with no access to the Ubuntu host (`sashi-llm`) that actually runs
Paperclip/Hermes. Every script here is meant to be copied over and executed
there, by you, after the manual steps below.

---

## What's verified vs. assumed

Be honest with yourself about this before running anything:

**Verified** (directly confirmed in `OPERATIONS.md`, which documents the
system as it actually runs, checked 2026-09-12):
- `paperclipai issue list -C <companyId> --api-key <key> --json` works and
  returns issues.
- `paperclipai approval create -C <companyId> --api-key <key> --type
  request_board_approval --requested-by-agent-id <id> --payload '{...}'
  --json` works, and an **agent-scoped key can call it** — only
  `approval approve`/`reject` require board access (403 otherwise).
- The company id (`0c265070-3974-497a-99ee-cf942ffe139d`, RSAData) and
  project id (`b9bb008e-7771-4bc7-aad8-71e2faa3307f`, "Always-On Engineering
  Fleet") are real and current. All work — across IBMiMCP, iNova, and the
  fleet's own repo — is scoped to this single Paperclip project.
- Every agent (Aaron/Dhira/Lynn/Sam) ends a run by setting a disposition via
  `node ./paperclip-task.mjs update-status --issue <id> --status <done|blocked|in_review> --comment "..."`,
  run from `/home/sashi/.hermes/skills/paperclip-task-bridge`. `in_review`
  specifically means "ready but needs a human or CTO look before it counts
  as done" — that's the exact hook this daemon uses.
- Services on this host run as **systemd --user units under `sashi`**, with
  linger enabled — not as separate per-service system accounts. This build
  follows that pattern rather than the generic separate-service-account
  model described earlier in the migration plan, because that model was
  never actually implemented on the real host.

**Assumed / not independently confirmed — verify before depending on them:**
- The exact `paperclipai` flag names used in `claude_supervisor.py` beyond
  what's quoted above (e.g. whether `issue list` takes `--project-id` or a
  differently-named flag, whether the JSON shape has `key`/`id`/`updatedAt`/
  `comments` fields exactly as the script expects). Run `paperclipai --help`,
  `paperclipai issue --help`, and `paperclipai issue list -C <companyId>
  --project-id <projectId> --json | head -c 2000` on the real host first,
  and adjust `claude_supervisor.py` if the shape differs — it's the only
  file that should need to change.
- Whether Paperclip issues carry any explicit link to a repo/commit. Nothing
  in `OPERATIONS.md` confirms this, so `find_repo_context()` falls back to a
  heuristic `git log --grep=<issue-key>` across the three known local repos.
  A miss is expected and handled (the review says so and lowers confidence),
  not a bug.
- Whether Hermes (the CLI, not Paperclip) can be configured to use Anthropic
  as a model provider directly, the same way `hermes_local` currently points
  at the local `llama-qwen.service` endpoint. If it can, that would be a
  cleaner integration than this standalone daemon — see "Alternative
  approach" below. This build does not depend on that being true.

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
3. **Get an Anthropic API key** for this purpose. Treat it like every other
   credential in `OPERATIONS.md`'s credentials table: never in Git, mode
   600, scoped to one service identity.
4. Record the new agent id and both API keys — you'll put them in
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

If Hermes turns out to support Anthropic as a first-class model provider
(the same way `hermes_local`'s `adapterConfig.model` currently points at
`qwen3-coder-30b-a3b-q4-k-xl`), a cleaner integration would be a *real*
Paperclip agent using the normal `hermes_local` heartbeat/task_bridge flow,
just pointed at Claude instead of the local model — no standalone daemon,
no separate polling loop, full reuse of the existing dispatch and reporting
mechanism. Check `hermes --help` / Hermes's own provider configuration docs
for this before assuming it isn't possible. If it is, this whole directory
becomes unnecessary and the "Adding a new agent" procedure in `OPERATIONS.md`
is all you need.
