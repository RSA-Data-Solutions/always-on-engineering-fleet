# Live Operations — Paperclip + Hermes Fleet

This documents the system as it actually runs today on `sashi-llm` (Ubuntu, 2× Intel Arc Pro B60),
following [`paperclip-hermes-always-on-engineering-fleet-migration-plan.md`](paperclip-hermes-always-on-engineering-fleet-migration-plan.md).
That file is the original proposal; this file is the as-built reference — where real IDs,
ports, and behavior diverged from the plan during implementation, this file wins.

Read `agents/*.md` for what each role is actually supposed to do. This file is about how
the pieces are wired together and how to operate them.

**Current as of 2026-09-30:** Paperclip was reinstalled (new company and agent IDs), everything runs
on the local model (Ram included), and Ram routes every handoff himself. The pipeline advancer and
Claude supervisor are switched off (their code is still in `scripts/setup/`, timers disabled).

---

## Architecture

```text
             Slack (RSADevBot) / Telegram
                       |
             Hermes Gateway (hermes-gateway.service)        Ram's Slack side
             persona = ~/.hermes/SOUL.md                    ram-file / ram-status / ram-answer
                       |
                   Paperclip (paperclipai.service, port 3100)
                   company "RSAData", project "AlwaysOnEngineeringFleet"
                       |
     Ram's Paperclip side (hermes_local, ~/.hermes)        routes: one child issue per stage
                       |
     Sam / Lynn / Aaron / Dhira (hermes_local, ~/.hermes-workers)
                       |
                   llama.cpp (llama-qwen.service, port 8080)
                   Qwen3-Coder-30B-A3B, 196K context, one request at a time
```

Ram has two sides that share one Hermes home (`~/.hermes`): the **gateway** process that talks on
Slack/Telegram, and **Paperclip runs** (`hermes_local`, a fresh `hermes` CLI process per heartbeat) that
route work. The workers run `hermes_local` through `~/.hermes-workers/bin/hermes-worker`, which gives
them their own Hermes home so they don't inherit Ram's persona.

Every path calls `llama-server` at `127.0.0.1:8080` (the public `https://aiweb.arunasasi.com/v1` is the
same server). It is `--parallel 1`, so requests queue; nothing is sent to a cloud model (Ram's Copilot
fallback was removed).

---

## Services

| Service | Unit | Port | Purpose | Status check |
|---|---|---|---|---|
| llama.cpp router | `llama-qwen.service` (systemd, `/etc/systemd/system/`) | 8080 | Loads one model at a time from `~/Documents/ai/models/presets.ini` | `systemctl status llama-qwen` |
| Paperclip | `paperclipai.service` (systemd --user) | 3100 | Org chart, issues, approvals, web UI | `paperclipai service status` |
| Hermes gateway | `hermes-gateway.service` (systemd --user) | 8642 (API), Slack/Telegram sockets | Ram on Slack/Telegram | `systemctl --user status hermes-gateway` |
| Hermes dashboard | `hermes-dashboard.service` (systemd --user) | 9119 | Hermes's own config/session web UI | `curl 127.0.0.1:9119` |
| ~~Pipeline advancer / Claude supervisor~~ | `pipeline-advancer.timer`, `claude-supervisor.timer` | — | **Disabled 2026-09-30** (not used in the new setup) | `systemctl --user is-enabled …` → `disabled` |

**llama.cpp model** (`qwen3-coder-30b-a3b-q4-k-xl`): all 48 layers on the GPUs, split by layer across
both B60s (`--split-mode layer --tensor-split 1,1`), `--ctx-size 196608`, f16 KV cache, flash attention.
Measured 2026-10-01: ~20.0 GiB used on SYCL0 and ~18.9 GiB on SYCL1 (16.5 GiB weights + 18.0 GiB KV +
buffers), leaving ~3.5 / ~5 GiB free. `presets.ini` also has a `-long` variant (tensor split, faster
above ~20K tokens of context, ~4 min to load).

Paperclip web UI: `http://127.0.0.1:3100` (LAN: `http://192.168.68.83:3100`, unreliable from other
machines — loopback/port-forward is the confirmed-working path). Hermes dashboard: `http://127.0.0.1:9119`.

---

## Org chart

| Agent | Paperclip agent ID | Role | Runs as | Reports to |
|---|---|---|---|---|
| Ram | `297c5b1e-1025-4b33-b4f7-c53ef02fb24c` | CTO, router | `hermes_local`, plain `hermes` (`~/.hermes`); can assign tasks | — |
| Sam | `43bacfa8-1edd-4299-87c8-e2438ac3a572` | Software Engineer | `hermes_local` via `hermes-worker`, toolsets `terminal,file` | Ram |
| Lynn | `fd64c507-364b-426b-b5d8-13a76f43142f` | QA Engineer | `hermes_local` via `hermes-worker`, toolsets `terminal,file` | Ram |
| Aaron | `26412e53-6692-4a6e-9a14-131cf7d6df05` | DevOps Engineer | `hermes_local` via `hermes-worker`, toolsets `terminal,file` | Ram |
| Dhira | `84997e0f-dbd1-4c0a-a2f6-b19a492cb43d` | Research | `hermes_local` via `hermes-worker`, toolsets `web,file` | Ram |

Company: `RSAData` (`f7aed163-5581-400d-8661-b8bbff78b849`).
Project: `AlwaysOnEngineeringFleet` (`5f3f828f-4224-4ed7-b4d6-845f86a64d80`) — every request lives here.

All five use model `qwen3-coder-30b-a3b-q4-k-xl` with provider `auto` (Hermes then uses its own
config: `provider: custom`, `base_url: http://127.0.0.1:8080/v1`, `context_length: 196608` in
`~/.hermes/config.yaml` and `~/.hermes-workers/config.yaml`). Every agent has `maxConcurrentRuns: 1`;
workers have `persistSession: false` and cannot create agents or assign tasks.

Each agent's instructions are a copy of `agents/<name>.md` (the live file is
`~/.paperclip/instances/default/companies/<company>/agents/<agentId>/instructions/AGENTS.md`).
**The repo file is the source of truth — editing `agents/*.md` does nothing to the live agent until
you copy it there** (see "Common operational commands"). Ram's Slack side follows `SOUL.md` instead
(versioned at `scripts/setup/ram-tools/SOUL.md`).

---

## Credentials — what exists and where, not the values

Never put actual key values in this repo or in Git. This table is a map of what exists,
not a place to record secrets.

| Credential | Used by | Lives in |
|---|---|---|
| llama-server API key | Anything calling llama-server directly | `/etc/default/llama-qwen` (mode 600); copies in `~/.hermes/config.yaml` and `~/.hermes-workers/config.yaml` |
| Paperclip board token | Operator CLI/admin use (`paperclipai connect --persona board`) | CLI context profile; revoke short-lived setup keys after use |
| Ram's standard key | Ram's Slack commands and `ram-paperclipai` outside a run | `~/.hermes/.env` (`PAPERCLIP_RAM_STANDARD_KEY`) |
| Ram's task-bridge key (`task_bridge`, scoped to the fleet project) | Filing issues for Ram only — **it cannot assign work to other agents** (`deny_scope`) | `~/.hermes/.env` (`PAPERCLIP_BRIDGE_API_KEY`) |
| Per-run agent key | Every Paperclip run (Ram's and the workers'): status updates, comments, and — for Ram — assigning stage issues | Injected by Paperclip as `PAPERCLIP_API_KEY` for that run only |
| Slack `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Gateway's Slack connection; `ram-reply` | `~/.hermes/.env` |
| `API_SERVER_KEY` | Gateway's own HTTP API (port 8642) | `~/.hermes/.env` |

**No secret belongs in `SOUL.md` or in an agent's instructions.** Ram's tools read keys from
`~/.hermes/.env` themselves, so the model never types one. Aaron's IBMiMCP `ADMIN_API_KEY` lives in
the git-ignored `contexts/ibmimcp.md`, not in `agents/aaron.md`.

---

## How a request gets done (Ram routes, since 2026-09-30)

```text
Slack → Ram (gateway)   ram-file: acknowledges, files ONE request issue assigned to Ram
                        (ORIGIN: slack thread_ts=…; refuses duplicates)
      → Ram (Paperclip) woken by the assignment; writes the spec as a comment; asks via ram-reply if unclear
      → [dev] Sam       child issue; Sam cuts his own worktree + branch rsa-NN, builds, commits,
                        runs install/typecheck/tests himself, sets done (or blocked + @Ram)
      → [qa] Lynn       tests in Sam's worktree against each acceptance criterion
                        (done = approve; blocked + code_bug → Ram sends a [dev] rework to Sam, max 2)
      → Ram merges      git merge --no-ff rsa-NN into main and pushes (only Ram merges)
      → [deploy] Aaron  deploys/verifies from main; git is read-only for him
      → Ram             ram-reply posts the result in the Slack thread; removes the worktree; closes
```

How Ram learns a stage finished: Paperclip wakes the owner of a parent issue when a child issue is
set `done` (`issue_children_completed`), and wakes an agent that is @mentioned in a comment
(`[@Ram](agent://<id>)`), which workers do when they set `blocked`. When the requester answers a
question in Slack, `ram-answer` records it on the request and wakes Ram directly.

| Piece | Does |
|---|---|
| Ram, Slack side (`SOUL.md`) | Front door. `ram-file`, `ram-status`, `ram-answer`; answers questions directly. |
| Ram, Paperclip side (`agents/ram.md`) | Spec, one stage at a time, merge, `ram-reply` to the requester, close. Uses `ram-paperclipai`. |
| Sam / Lynn / Aaron / Dhira | Do their stage, set `done` / `blocked`. Never assign onward. |

Ram's commands live in `~/.hermes/bin` (source and tests: `scripts/setup/ram-tools/`, see its README).
Tests: `cd scripts/setup/ram-tools && python3 -m unittest test_ram_tools`.

Verified end to end: RSA-3/RSA-4 (Ram creates a stage for Sam, Sam finishes, Ram closes) and RSA-5
(`ram-file` → Paperclip Ram → `ram-reply` posted to Slack).

### What the removed automation used to do (now nobody does it)

- **Build gate:** Sam must run install/typecheck/tests himself; nothing re-checks before Lynn.
- **Claude spec and code review:** Ram writes the spec; Lynn's tests are the only review.
- **Disposition checks:** a worker run that ends without setting a status is left for Paperclip's own
  recovery (it marks the issue `blocked`); Ram is only woken if the worker @mentions him.
- **Cloud route** for tasks too big for the local model: gone; a task that keeps failing needs a human.

### Hard-won rules (each one is a real failure)

- **Workers have their own Hermes home** (`~/.hermes-workers`, neutral persona, own memory). Until
  2026-09-24 every worker session carried Ram's SOUL.md ("You are Ram, CTO") because all agents
  shared `~/.hermes`.
- **One stage at a time across the fleet.** llama.cpp serves one request at a time; three concurrent
  Sam runs once starved each other into 30-minute timeouts. Ram keeps only one child issue `todo` or
  `in_progress`.
- **Set the model explicitly on every agent.** With no `model` in the adapter config Paperclip sends
  the literal string `"auto"`, and llama.cpp rejects it (`model 'auto' not found`) — Ram's first run
  on 2026-09-30 failed this way.
- **New dependencies must be real.** Sam once imported an npm package that does not exist (`mapepire`;
  the real one is `@ibm/mapepire-js`) and mocked unit tests would have passed it.
- **Ram's tools refuse workers.** Mixing Ram's key with a worker's run id is rejected by Paperclip as
  "no valid run" — that silently broke every worker's `update-status` on 2026-09-23.
- **`PAPERCLIP_API_URL` in `~/.hermes/.env` ends in `/api`**; the `paperclipai` CLI appends `/api`
  itself, so the wrappers unset it (otherwise every call 404s).
- **Slack sessions are per thread and frozen at start.** A Hermes session keeps the system prompt it
  started with; after editing SOUL.md, restart the gateway AND start a new thread (or `/new`).
- **Hermes updates itself.** On 2026-09-30 an update landed while the gateway was running; it
  restarted mid-update and every Slack message failed with an `ImportError`. If Ram goes silent after
  an update, restart `hermes-gateway.service`.

---

## Approvals

**Routine work** (file a request, route a stage, change a status) — Ram or a report just does it and
reports what happened. If a request is ambiguous, Ram asks the requester (`ram-reply`) and waits —
a prompt-level convention, not something Paperclip enforces.

**High-stakes actions** (release, hiring an agent, budget changes) — these use Paperclip's formal
approval object:

```bash
~/.hermes/bin/ram-paperclipai approval create -C f7aed163-5581-400d-8661-b8bbff78b849 \
  --type request_board_approval --requested-by-agent-id 297c5b1e-1025-4b33-b4f7-c53ef02fb24c \
  --payload '{"summary":"...","action":"..."}' --json
```

This is a hard boundary, not policy: an agent key gets `403: Board access required` on
`approval approve`/`approval reject`. Only a board-authenticated identity (a human in the Paperclip
web UI, or a board token in a CLI session) can decide. A human saying "approved" in Slack does
**not** let Ram execute a high-stakes action himself.

Check pending approvals: `paperclipai approval list -C f7aed163-5581-400d-8661-b8bbff78b849`.

---

## Known limitations

- **The local model (Qwen3-Coder-30B-A3B) is not fully reliable for multi-step orchestration** — and
  Ram now orchestrates on it. Observed failure modes: fabricating status, creating duplicate tasks,
  and trying to *edit* `paperclip-task.mjs` instead of running it. Ram's Slack commands exist to make
  filing and status deterministic; treat Ram's narrated claims as a starting point and verify with
  `ram-status` or the Paperclip UI.
- **The "wake Ram when a child finishes" path is built but was not exercised live yet** — in the
  routing test Ram waited inside his first run instead. If Ram doesn't pick up the next stage on his
  own, check `agent_wakeup_requests` for `issue_children_completed`.
- **LAN exposure of the Paperclip UI from other devices has been unreliable** — loopback access (via
  SSH/VS Code port-forwarding) is the confirmed-working path. Not root-caused.
- **`hooks_auto_accept: true`** is enabled for the Hermes gateway so it can run shell commands without
  an interactive TTY approval (an explicit trade-off, matching upstream's headless recommendation).
- **Two `llama-server` processes appear in `ps`** — the router (`llama-qwen.service`) and its model
  child. Only one model is ever resident in VRAM. Do not stop the child directly.

---

## Common operational commands

```bash
# Service health
systemctl status llama-qwen
paperclipai service status
systemctl --user status hermes-gateway
journalctl --user -u hermes-gateway.service -f

# What is in flight (as Ram sees it)
~/.hermes/bin/ram-status
~/.hermes/bin/ram-status RSA-NN

# All issues
paperclipai issue list -C f7aed163-5581-400d-8661-b8bbff78b849 --json

# Restart the gateway after editing SOUL.md, config.yaml, or .env (then start a new Slack thread)
systemctl --user restart hermes-gateway.service

# Push an updated agents/<name>.md into its live agent
cp agents/<name>.md ~/.paperclip/instances/default/companies/f7aed163-5581-400d-8661-b8bbff78b849/agents/<agentId>/instructions/AGENTS.md

# Reinstall Ram's commands and SOUL.md from this repo
cd scripts/setup/ram-tools && cp ram_common.py ram-file ram-status ram-answer ram-reply ram-paperclipai ~/.hermes/bin/ \
  && chmod +x ~/.hermes/bin/ram-* && cp SOUL.md ~/.hermes/SOUL.md

# Manually trigger an agent's heartbeat
paperclipai agent heartbeat:invoke <agentId>

# Pending approvals
paperclipai approval list -C f7aed163-5581-400d-8661-b8bbff78b849
```

---

## Adding a new agent

1. Write `agents/<name>.md` in this repo — profile, inputs, job steps, and a "Reporting back to
   Paperclip" section modeled on the existing ones (which statuses apply and when; mention Ram when
   `blocked`).
2. Create the Paperclip agent: adapter "Hermes" (`hermes_local`), Command
   `/home/sashi/.hermes-workers/bin/hermes-worker`, Model `qwen3-coder-30b-a3b-q4-k-xl` (never leave it
   unset), Provider `Auto`, Persist session off, reports to Ram. Then set `maxConcurrentRuns: 1` and
   turn off "can create agents" / "can assign tasks".
3. Copy `agents/<name>.md` into the agent's `instructions/AGENTS.md`.
4. No per-agent key is needed: Paperclip injects a run key, which the task-bridge script uses for
   status updates and comments.
5. Add the agent to Ram's team table in `agents/ram.md` and to `AGENTS` in
   `scripts/setup/ram-tools/ram_common.py`, then reinstall both.
