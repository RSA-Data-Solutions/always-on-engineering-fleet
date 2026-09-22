# Build plan — Paperclip install + Hermes onboarding (Stage 2)

This replaces the guessed Docker/Postgres sketch in the migration plan's
"Paperclip deployment" / "Hermes deployment" sections. Those were illustrative
placeholders written before anyone had confirmed what Paperclip actually is.
Everything below is transcribed from the real project:
[`paperclipai/paperclip`](https://github.com/paperclipai/paperclip) (81k★, MIT,
"the open-source app people use to manage AI agents at work" — a Node.js
server + React UI with an embedded Postgres, no external DB setup needed) —
specifically `doc/CLI.md` and `doc/HERMES_GATEWAY_ONBOARDING.md` in that repo.
Re-verify against those files directly if anything below seems off; this was
transcribed on 2026-09-21 and the project moves fast.

## Verified starting state (2026-09-21, `sashi-llm`)

- GPU + llama.cpp + Qwen3-Coder-30B-A3B: **running**.
- Hermes Agent v0.21.4 (install method: git, at `~/.hermes/hermes-agent`):
  **installed**, and already configured — `~/.hermes/SOUL.md`,
  `~/.hermes/config.yaml`, and `~/.hermes/.env` all exist, and Hermes skills
  already include `paperclip` and `paperclip-task-bridge`. Ram's persona was
  apparently set up in anticipation of this, even though Paperclip itself was
  never installed.
- Paperclip: **not installed**. Everything in `OPERATIONS.md` that depends on
  it (company/project/agent IDs, task_bridge keys, the approval workflow) is
  aspirational, not real, until this is done.
- The three repos (IBMiMCP, iNova, this fleet repo) are present under
  `/home/sashi/Documents/projects/RSA/`, matching `contexts/*.md`.

## Step 1 — Install Paperclip

```bash
curl -fsSLO https://paperclip.ing/install.sh
curl -fsSLO https://paperclip.ing/install.sh.sha256
sha256sum -c install.sh.sha256
bash install.sh
```

Requires Node.js 24.11+; the installer bootstraps it if missing. This installs
a managed `paperclipai` CLI under `~/.paperclip/cli` with a shim at
`~/.local/bin/paperclipai`, and can install a systemd **user** service (Linux)
— this part of `OPERATIONS.md` was directionally correct, just premature.

For a non-interactive install (matching this repo's confirm-heavy scripting
style) instead of the interactive wizard:

```bash
curl -fsSL https://paperclip.ing/install.sh | bash -s -- --no-prompt --no-onboard
paperclipai onboard --yes --install-service   # --install-service is never implied by --yes
```

Verify:

```bash
paperclipai service status
curl -s http://127.0.0.1:3100/api/health
```

Onboarding creates a company and a first (CEO) agent. Get the company id you'll
need for every command below:

```bash
paperclipai company list
```

**Security note for anything built on top of this**: use `npx paperclipai
<command>` (or the installed `paperclipai` shim directly) for any argument that
might contain issue text, comments, or model output. Never `pnpm paperclipai
...` with untrusted content interpolated into the command string — `pnpm`
builds a shell command, so a crafted value can run arbitrary commands or leak
an env var. `claude_supervisor.py` already does this correctly (Python
`subprocess.run` with an argument list, never `shell=True`) — keep it that way
in anything else that shells out to `paperclipai`.

## Step 2 — Onboard Ram as `hermes_gateway`

Ram is the one that should run as a persistent gateway (Slack/Telegram, "Ram"
persona) rather than a per-heartbeat local process — matches `OPERATIONS.md`'s
description and the fact that SOUL.md already exists.

```bash
# distinct from the Paperclip agent key claimed later — do not reuse
export API_SERVER_KEY=$(openssl rand -hex 32)
API_SERVER_ENABLED=true hermes gateway run --replace --accept-hooks
```

Then, from wherever you're running `paperclipai` (needs a board-authenticated
session or token — `paperclipai whoami` to check):

```bash
paperclipai invite create --company-id <company-id> --payload-json '{"requestType":"agent"}'
paperclipai invite show <token>
```

Submit the join request (Hermes-side — see
[`HERMES_GATEWAY_ONBOARDING.md`](https://github.com/paperclipai/paperclip/blob/master/doc/HERMES_GATEWAY_ONBOARDING.md)
for the exact endpoint if this needs to be scripted rather than pasted from the
onboarding text) with:

```json
{
  "requestType": "agent",
  "agentName": "Ram",
  "adapterType": "hermes_gateway",
  "capabilities": "Hermes gateway agent with code, browser, web, and file tools.",
  "agentDefaultsPayload": {
    "apiBaseUrl": "http://127.0.0.1:8642",
    "apiKey": "<same value as API_SERVER_KEY>",
    "paperclipApiUrl": "http://127.0.0.1:3100",
    "sessionKeyStrategy": "issue"
  }
}
```

Approve and claim:

```bash
paperclipai join list --company-id <company-id> --status pending_approval
paperclipai join approve <request-id> --company-id <company-id>
paperclipai join claim-key <request-id> --claim-secret <secret>
```

Store the claimed key in Hermes's own secret store (`~/.hermes/.env` or
wherever `config.yaml` expects it) as `PAPERCLIP_API_KEY` — **not** the same
value as `API_SERVER_KEY`. These authenticate traffic in opposite directions
and must stay distinct.

## Step 3 — Onboard Aaron/Dhira/Lynn/Sam as `hermes_local`

`hermes_local` means Paperclip shells out the `hermes` CLI as a child process
per heartbeat — no separate gateway process needed for these four. The exact
`agentDefaultsPayload` shape for `hermes_local` wasn't in the section quoted
above; check it before scripting this:

```bash
paperclipai adapter config-schema hermes_local
```

Then, per agent (repeat for Aaron, Dhira, Lynn, Sam):

```bash
paperclipai agent create --company-id <company-id> \
  --payload-json '{"name":"Aaron","adapterType":"hermes_local","reportsTo":"<Ram agent id>"}'
paperclipai agent instructions-file:put <agentId> --path AGENTS.md --content-file agents/aaron.md
paperclipai token agent create --company-id <company-id> --agent <agentId> --name self
```

The `token agent create` output is that agent's own scoped API key — wire it
into whatever env Hermes's `hermes_local` invocation reads for
`PAPERCLIP_BRIDGE_API_KEY`/`PAPERCLIP_AGENT_ID`/etc. (matches the credential
table already documented in `OPERATIONS.md`, which got this part right even
though Paperclip wasn't installed yet).

## Step 4 — Verify with one real task before trusting anything

```bash
paperclipai issue create --company-id <company-id> --title "Smoke test" --status todo
paperclipai issue list --company-id <company-id> --status todo
```

Confirm Paperclip's heartbeat scheduler actually picks it up and invokes the
assigned agent, and that the agent's disposition (`done`/`blocked`/`in_review`)
lands back correctly, before wiring up Slack/real work.

## Open questions to resolve on the real CLI before automating further

- **Exact `hermes_local` config fields** — `paperclipai adapter config-schema hermes_local`.
- **Whether `claude_local` supports restricting tool access.** Paperclip ships
  a native `claude_local` adapter (harness `claude`, credential
  `ANTHROPIC_API_KEY`) that runs the `claude` CLI directly, the same way
  `hermes_local` runs `hermes`. If `paperclipai adapter config-schema
  claude_local` shows a way to restrict tools/permissions per-agent, Claude
  Supervisor (`scripts/setup/claude-supervisor/`) should probably become a
  native `claude_local` Paperclip agent instead of the standalone polling
  daemon it is today — that would replace a bespoke poll loop with the same
  native heartbeat mechanism every other agent already uses. **Don't make that
  switch until the tool-restriction question is answered** — the standalone
  daemon's `--disallowedTools` lockdown is the only thing currently keeping
  Claude Supervisor advisory-only, and the native adapter's default tool
  access (full Claude Code — Bash, Read, Write, Edit) would defeat that if
  there's no config knob for it.
- **The full `approval create --type` enum** — only `hire_agent` appears in
  the docs as an example; `paperclipai openapi` dumps the real schema.

## Corrections this made to `scripts/setup/claude-supervisor/`

`claude_supervisor.py` was written against guessed CLI flags before any of
this was confirmed. Real flags differ in three places, now fixed:
- `-C <id>` → `--company-id <id>` everywhere.
- `issue list` has no `--project-id` flag — it takes `--status`,
  `--assignee-agent-id`, `--match`. Filtering is now by `--status in_review`
  directly (simpler than the client-side filter this had before).
- `approval create` takes `--type <type> --payload '<json>' [--issue-ids
  <id>]`, not `--payload-json` and not a `--requested-by-agent-id` flag —
  identity comes from which API key authenticates the call.
