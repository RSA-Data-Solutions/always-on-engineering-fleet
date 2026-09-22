# Handoff — Paperclip/Hermes live build, continuing on the Ubuntu host

## Your job

Continue standing up the real Paperclip + Hermes fleet on `sashi-llm` (this
machine). This was being driven from a Mac Claude Code session with no SSH
access to this host; the user is now working directly with Claude Code here.
Pick up from the current blocker below, verify as you go, and don't trust
this repo's own docs blindly — several of them turned out to be aspirational
rather than accurate (see "Known trust issues" below).

## Quick context

The user (Sashi) is building an always-on AI engineering fleet — five agents
(Ram, Aaron, Dhira, Lynn, Sam) doing continuous QA/fix/research work across
three repos (IBMiMCP, iNova, and this fleet repo itself), managed by
[Paperclip](https://github.com/paperclipai/paperclip) (open-source agent
orchestration, 81k★, MIT) and executed via
[Hermes](https://github.com/paperclipai/paperclip) — actually a separate
project, `hermes-agent` (installed via git at `~/.hermes/hermes-agent`).
On top of that, a new **Claude Supervisor** role is being added: an
advisory-only reviewer (no shell, no repo writes) that gives a second opinion
on the local model's work before it reaches a human.

## Current verified state (2026-09-21)

- GPU + llama.cpp + Qwen3-Coder-30B-A3B-Q4_K_XL: running (backend is
  **Vulkan**, confirmed via the live systemd unit and `/props` — not SYCL,
  despite an earlier assumption in this repo's history).
- Hermes Agent v0.21.4 (install method: git, at `~/.hermes/hermes-agent`):
  installed, with `~/.hermes/SOUL.md`, `~/.hermes/config.yaml`,
  `~/.hermes/.env` already present, and Hermes skills already include
  `paperclip` and `paperclip-task-bridge`.
- **Paperclip: now installed and running** (confirmed by the user — this was
  the missing piece; see "Known trust issues" below for why that mattered).
- The three repos are present under `/home/sashi/Documents/projects/RSA/`.

## Current blocker (pick up here)

Trying to get a `hermes_local` Paperclip agent to heartbeat fails with:

```
Failed to start command "hermes" in ".". Verify adapter command, working
directory, and PATH (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin:/snap/bin).(adapter_failed)
```

This is a `child_process.spawn` failure (command not found), not a Hermes
runtime error — `hermes --version` works fine in an interactive shell, but
Paperclip's systemd **user** service gets the bare minimal PATH shown above,
which almost certainly doesn't include wherever `hermes`'s actual executable
lives (a git-based Python install — likely `~/.local/bin` or inside
`~/.hermes/hermes-agent`'s own venv).

Two things to check, in this priority order:

1. **Find the real path and check for a per-agent override (preferred):**
   ```bash
   command -v hermes
   paperclipai adapter config-schema hermes_local
   ```
   If that schema has a `command`/`binPath`/`cwd`/`env` field, set the
   agent's config to the absolute path from `command -v hermes` instead of
   relying on bare `hermes` + PATH. More robust than patching the whole
   service's environment.

2. **If there's no such field, fix it at the systemd service level:**
   ```bash
   systemctl --user cat paperclipai   # find the actual unit file
   ```
   Add the directory containing `hermes` to that unit's
   `Environment=PATH=...` (prepend to the existing default PATH, don't
   replace it), then:
   ```bash
   systemctl --user daemon-reload
   systemctl --user restart paperclipai
   ```

## What comes after the PATH fix, in order

1. Confirm at least one `hermes_local` agent heartbeats successfully (no
   `adapter_failed`), then verify end-to-end with one real issue:
   ```bash
   paperclipai issue create --company-id <company-id> --title "Smoke test" --status todo
   ```
   Watch it get picked up and worked, and confirm the disposition
   (`done`/`blocked`/`in_review`) lands back correctly.
2. Onboard Ram specifically as `hermes_gateway` (persistent process,
   Slack/Telegram — different from the other four, which are `hermes_local`).
   Full documented procedure: `scripts/setup/paperclip-hermes/README.md`
   (Step 2), sourced directly from upstream's
   `doc/HERMES_GATEWAY_ONBOARDING.md`.
3. Onboard Aaron/Dhira/Lynn/Sam as `hermes_local` and push their real
   instructions bundles:
   ```bash
   paperclipai agent instructions-file:put <agentId> --path AGENTS.md --content-file agents/aaron.md
   ```
   (repeat per agent). `scripts/setup/paperclip-hermes/README.md` Step 3.
4. Once the live fleet is confirmed working for real, build Claude
   Supervisor: `scripts/setup/claude-supervisor/README.md`. **Before
   installing it**, run `paperclipai adapter config-schema claude_local` —
   if it supports restricting tool access, Claude Supervisor should become a
   native `claude_local` Paperclip agent instead of the standalone polling
   daemon that's currently built. Don't make that switch if tool restriction
   isn't confirmed — the daemon's explicit `--disallowedTools` lockdown is
   the only thing currently guaranteeing "advisory only, no shell."
5. Once everything above is verified against reality, update `OPERATIONS.md`
   to match — it currently describes the org chart as already live, which
   wasn't true as of this handoff. Don't just delete the inaccurate parts;
   correct them against what you've actually verified.

## Known trust issues — read before trusting anything else in this repo

- **`OPERATIONS.md` claimed Paperclip was already live** (real company/agent
  UUIDs, a working approval workflow, the whole org chart) when it actually
  wasn't installed at all. The infrastructure claims (GPU, llama.cpp, model,
  Hermes install, repo paths) turned out accurate; everything downstream of
  Paperclip did not. Verify each remaining claim in it against the live
  system rather than assuming the rest is accurate just because some of it
  was.
- **CLI command examples elsewhere in this repo's docs were guessed and
  wrong** (e.g. `-C` instead of `--company-id`, a nonexistent `--project-id`
  filter on `issue list`, an invented `--requested-by-agent-id` flag on
  `approval create`). These have been fixed in `claude_supervisor.py` and
  `scripts/setup/paperclip-hermes/README.md` against the real upstream
  `doc/CLI.md`, but if you hit a flag mismatch anywhere else, the real
  project (`github.com/paperclipai/paperclip`, `doc/CLI.md` and
  `doc/HERMES_GATEWAY_ONBOARDING.md`) is the source of truth — re-fetch it,
  it moves fast, don't assume this repo's transcription is still current.
- **The hardware backend was misreported once too**: an early draft of the
  migration plan assumed SYCL; the actual production backend is Vulkan. Now
  corrected in `paperclip-hermes-always-on-engineering-fleet-migration-plan.md`.

## Reference files

- `paperclip-hermes-always-on-engineering-fleet-migration-plan.md` — overall
  design, including the "Claude Supervisor role" section
- `scripts/setup/paperclip-hermes/README.md` — real Paperclip install +
  Hermes onboarding steps
- `scripts/setup/claude-supervisor/` — the Claude Supervisor build
  (`README.md`, `claude_supervisor.py`, systemd unit, install/verify
  scripts) — blocked until the agents above heartbeat for real
- `agents/*.md` — role specs for Ram/Aaron/Dhira/Lynn/Sam/claude-supervisor
- `contexts/*.md` — per-project details (IBMiMCP, iNova, self-improvement)
- `OPERATIONS.md` — treat as unverified until you've re-checked it (see
  above)

## Things to NOT do

- Do not modify `agents/*.md` directly without going through the
  self-improvement loop (`contexts/self-improvement.md`) — this repo's
  standing rule (`CLAUDE.md`), for actual behavior/instruction changes. Infra
  debugging (systemd units, adapter config) isn't covered by that rule.
- Do not switch Claude Supervisor to the native `claude_local` adapter without
  confirming tool-access restriction is possible — see step 4 above.
- Do not assume any command example elsewhere in this repo (including
  `OPERATIONS.md`) is correct without checking it against the real,
  currently-running Paperclip instance or its upstream docs.

## If something feels off

If the live system's state diverges from what this handoff describes —
services that should be running aren't, agent IDs that don't match, config
that looks hand-edited since this was written — stop and ask the user before
proceeding. This build has already had two rounds of "the docs say X, reality
is Y"; assume there will be a third before assuming there won't.
