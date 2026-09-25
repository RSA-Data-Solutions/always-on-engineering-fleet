# Live Operations — Paperclip + Hermes Fleet

This documents the system as it actually runs today on `sashi-llm` (Ubuntu, Intel Arc B60),
following [`paperclip-hermes-always-on-engineering-fleet-migration-plan.md`](paperclip-hermes-always-on-engineering-fleet-migration-plan.md).
That file is the original proposal; this file is the as-built reference — where real IDs,
ports, and behavior diverged from the plan during implementation, this file wins.

Read `agents/*.md` for what each role is actually supposed to do. This file is about how
the pieces are wired together and how to operate them.

---

## Architecture

```text
                    Slack (RSADevBot) / Telegram
                              |
                    Hermes Gateway (hermes-gateway.service)
                    one persistent process, port 8642
                    persona = ~/.hermes/SOUL.md ("Ram")
                              |
                    paperclip-task-bridge skill
                    (~/.hermes/skills/paperclip-task-bridge)
                              |
                          Paperclip
                    (paperclipai.service, port 3100)
                    company "RSAData", project
                    "Always-On Engineering Fleet"
                              |
              issues assigned to Aaron / Dhira / Lynn / Sam
                              |
              each agent's own hermes_local run (Paperclip
              shells out `hermes` per heartbeat, not the
              gateway process)
                              |
                          llama.cpp
              (llama-qwen.service, port 8080, Qwen3-Coder-
               30B-A3B, 98K context, single request at a time)
```

Two separate Hermes execution paths hit the same model:

- **`hermes_local`** — what Aaron, Dhira, Lynn, and Sam run on. Paperclip shells out a
  fresh `hermes` CLI process per heartbeat. This is the path that does the actual
  engineering work (reading files, patching code, running tests).
- **`hermes_gateway`** — one persistent process (`hermes-gateway.service`) that owns the
  Slack/Telegram connections and answers as "Ram." It never edits code itself — it only
  reads status and delegates via the task-bridge skill.

Both ultimately call `llama-server` at `127.0.0.1:8080`, which is `--parallel 1` — every
request queues, so having two execution paths does not risk GPU over-subscription.

---

## Services

| Service | Unit | Port | Purpose | Status check |
|---|---|---|---|---|
| llama.cpp router | `llama-qwen.service` (systemd, `/etc/systemd/system/`) | 8080 | Serves Qwen3-Coder-30B-A3B, `-c 98304`, `-fa`, quantized KV cache | `systemctl status llama-qwen` |
| Paperclip | `paperclipai.service` (systemd --user) | 3100 | Org chart, issues, approvals, web UI | `paperclipai service status` |
| Hermes gateway | `hermes-gateway.service` (systemd --user) | 8642 (API), Slack/Telegram sockets | "Ram" persona, Slack/Telegram bot, task delegation | `hermes gateway status` |
| Hermes dashboard | `hermes-dashboard.service` (systemd --user) | 9119 | Hermes's own config/session web UI | `curl 127.0.0.1:9119` |

All four are `Restart=always` and survive logout/reboot (linger enabled for `sashi`).

Paperclip web UI: `http://127.0.0.1:3100` (LAN: `http://192.168.68.83:3100`, but LAN
access has been unreliable from outside this host — loopback/port-forward is the
confirmed-working path). Hermes dashboard: `http://127.0.0.1:9119`.

---

## Org chart

| Agent | Paperclip agent ID | Role | Adapter | Reports to |
|---|---|---|---|---|
| Ram | `093a44a5-da1d-421a-9708-cd1f05e6d734` | cto | `hermes_gateway` persona (SOUL.md) + standalone `hermes_local` entry | — |
| Aaron | `a02a6b9e-4d44-4f46-b373-83c15e6309c0` | devops | `hermes_local` | Ram |
| Dhira | `db976f2e-e1ca-432f-b6b4-4aa2c5d302b1` | researcher | `hermes_local` | Ram |
| Lynn | `d053dfe0-dbd6-45fd-8069-32b51a00580e` | qa | `hermes_local` | Ram |
| Sam | `ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0` | engineer | `hermes_local` | Ram |

Company: `RSAData` (`0c265070-3974-497a-99ee-cf942ffe139d`).
Project: `Always-On Engineering Fleet` (`b9bb008e-7771-4bc7-aad8-71e2faa3307f`) — every
task created through Slack/task-bridge is scoped to this one project.

Each agent's Paperclip `instructionsBundle` is a copy of its `agents/<name>.md` file from
this repo (pushed via `paperclipai agent instructions-file:put`). **The repo file is the
source of truth — editing `agents/*.md` here does nothing to the live agent until you
re-push it:**

```bash
paperclipai agent instructions-file:put <agentId> --path AGENTS.md --content-file agents/<name>.md
```

---

## Credentials — what exists and where, not the values

Never put actual key values in this repo or in Git. This table is a map of what exists,
not a place to record secrets.

| Credential | Used by | Lives in |
|---|---|---|
| `LLAMA_API_KEY` | Anything calling llama-server directly | `/etc/default/llama-qwen` (mode 600, owned by `sashi`) |
| Paperclip board token | This Claude Code session / CLI admin use | `~/.paperclip/auth.json` |
| Ram's task-bridge key (`task_bridge`, scoped to the fleet project, can assign to all 4 reports) | Ram's delegation (`create-task`, `comment`, `update-status`), via `~/.hermes/bin/ram-task` | Ram's Paperclip `adapterConfig.env.PAPERCLIP_BRIDGE_API_KEY` and `~/.hermes/.env` (`PAPERCLIP_BRIDGE_API_KEY`, read by the task-bridge script from the environment) |
| Ram's standard key (broad read, cannot approve/reject) | `paperclipai issue list` / `approval create`, via `~/.hermes/bin/ram-paperclipai` | `~/.hermes/.env` (`PAPERCLIP_RAM_STANDARD_KEY`) and Ram's `adapterConfig.env.PAPERCLIP_API_KEY` |
| Each of Aaron/Dhira/Lynn/Sam's own `task_bridge` key (scoped to themselves only) | Self-reporting disposition (`update-status`, `comment`) on their own assigned issues | Each agent's own `adapterConfig.env.PAPERCLIP_BRIDGE_API_KEY` |
| `API_SERVER_KEY` | Gateway's own HTTP API (port 8642) | `~/.hermes/.env` |
| Slack `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Gateway's Slack connection | `~/.hermes/.env` |

**No secret belongs in `~/.hermes/SOUL.md`** (2026-09-23; it used to inline Ram's standard key
because the model wasn't reliably expanding `$VAR` when composing commands). Keys now live in
`~/.hermes/.env` (mode 600). To keep the model from ever having to type or expand one, the
standard key is applied by a wrapper, `~/.hermes/bin/ram-paperclipai`, which reads
`PAPERCLIP_RAM_STANDARD_KEY` from that file and calls `paperclipai --api-key …`; SOUL.md just
tells Ram to run every `paperclipai` command through it. Likewise task creation goes through
`~/.hermes/bin/ram-task`, which loads the four `PAPERCLIP_*` bridge settings from `.env` itself and
execs `paperclip-task.mjs`. **Ram must not call `paperclip-task.mjs` directly:** on 2026-09-23 he ran
it inside `execute_code`, whose sandbox has no `PAPERCLIP_BRIDGE_API_KEY`, got "key is required",
and concluded he "cannot create tasks" — writing a proposal file instead of filing anything. The
wrapper makes it work from any tool, and SOUL.md now has a "never fake it" section (a task exists
only if `ram-task` printed its identifier; show errors, don't substitute a document). To rotate Ram's standard key, mint a
new one, update `.env` (and Ram's `adapterConfig.env.PAPERCLIP_API_KEY`), and revoke the old.

---

## Workflow: a Slack request becomes finished work

1. Human messages Ram in Slack (DM or `@mention`).
2. Hermes gateway wakes with `hermes-slack` toolset (full tool access; terminal has
   built-in dangerous-command checks). SOUL.md is loaded as Ram's identity for every run,
   regardless of platform.
3. For a status question, Ram runs `paperclipai issue list -C <companyId> --api-key
   <standard key> --json` — **not** `list-assigned`, which only ever shows issues assigned
   to Ram himself and will always be empty.
4. For a request to get something done, Ram creates a Paperclip issue via the
   `paperclip-task-bridge` skill, assigned to the right report, scoped with
   `--project-id b9bb008e-...`.
5. Paperclip's own heartbeat scheduler (~30s interval) picks up the new `todo` issue and
   invokes that agent's `hermes_local` run automatically — no manual trigger needed.
6. The assigned agent (Sam, say) does the actual work: reads files, patches code, runs
   commands, using its own scoped `task_bridge` key.
7. **Before the run ends, the agent must set a disposition** — `done`, `blocked`, or
   `in_review` via `update-status`. If a run exits successfully without one, Paperclip's
   own recovery logic auto-escalates the issue to `blocked` regardless of whether the work
   actually succeeded. This is enforced by Paperclip, not a courtesy — see "Reporting back
   to Paperclip" in each `agents/*.md` file.
8. Ram reports back to the human in Slack. **Take Ram's own narration with skepticism** —
   see Known limitations below. (For build/fix/change requests, steps 4-8 are replaced by the
   delivery pipeline below: Ram files the request, the Advancer routes it, and the final result
   is posted by the Advancer in Ram's name.)

---

## Delivery pipeline (Slack request → merged → deployed → reported back)

The as-built flow for any *build / fix / change* request. (Questions and research are just answered by Ram.)

```text
Slack → Ram (Claude)   ram-file: acknowledges, files epic + request (refuses duplicates)
      → Claude spec review     enhances the request; picks the owning project
                               (needs-clarification → asks you in Slack; you answer Ram → ram-answer)
      → git worktree + branch  cut from origin/main for THIS issue (~/.fleet-worktrees/<repo>/RSA-NN)
      → Sam                    builds in the worktree, commits with the issue key
      → build gate             deterministic: npm install (if deps changed) · typecheck · tests
                               (fail → straight back to Sam with the output; Claude/Lynn never see it)
      → Claude code review     the branch diff vs main against the request; writes test requests
                               (rework → Sam; can't verify → asks you)
      → Lynn                   tests in the worktree (done = approve; code_bug → Sam)
      → MERGE                  branch → main, pushed to origin (production deploy is your CI/CD)
      → Aaron                  deploys/verifies from main; git is read-only for him
      → Ram                    posts the result in the origin Slack thread; issue + epic closed
```

| Piece | Runs as | Does |
|---|---|---|
| Ram | Hermes gateway on **Claude Sonnet 5** (`~/.hermes`), persona in `~/.hermes/SOUL.md` | Front door. Three commands only: `ram-file`, `ram-status`, `ram-answer` (in `~/.hermes/bin`, source in `scripts/setup/ram-tools/`). Never assigns work himself. |
| Claude Supervisor | `claude-supervisor.timer` (30s) → `claude_supervisor.py` | Writes spec reviews, code reviews (from the worktree diff) and disposition checks as comments. |
| Pipeline Advancer | `pipeline-advancer.timer` (30s) → `pipeline_advancer.py` (+ `pipeline_git.py`, `pipeline_gate.py`) | The only router: worktrees, queue, gate, handoffs, merge, final Slack post. Run-locked; 900s timeout. |
| Sam / Lynn / Aaron | `hermes_local` via `~/.hermes-workers/bin/hermes-worker` | Do their stage, set `done`/`blocked`. Never assign onward. |

Full stage map and design reasons: `scripts/setup/pipeline-advancer/README.md`. Offline tests (90 tests, real git
repos for the git/gate logic): `cd scripts/setup/pipeline-advancer && python3 -m unittest discover -p "test_*.py"`
and `cd scripts/setup/ram-tools && python3 -m unittest test_ram_tools`.

### Hard-won rules (each one is a real failure from 2026-09-22..24)

- **Workers have their own Hermes home** (`~/.hermes-workers`, neutral persona, own memory). Until 2026-09-24
  every worker session carried Ram's SOUL.md ("You are Ram, CTO") because all agents shared `~/.hermes`.
  Sam/Lynn/Aaron/Dhira reach it via `adapterConfig.hermesCommand`; `persistSession` is off and
  `maxConcurrentRuns` is 1. (Dhira additionally has `worktreeMode: true` outside a git repo and fails at start — unrelated, unfixed.)
- **One pipeline issue per agent at a time.** llama.cpp serves one request at a time (`--parallel 1`); three
  concurrent Sam runs starved each other into 30-minute timeouts. Extra issues wait in `backlog` with
  `[pipeline-stage: queue-<role>]` and start automatically, oldest first.
- **Silent runs are judged, not trusted.** A local model that ends a run without a status makes Paperclip demand
  a "board decision". The advancer sends such issues (and `in_progress` ones with no live run for
  `PIPELINE_STALL_MINUTES`=20) to Claude for a **disposition check**; complete/failed/unclear then routes normally.
- **Nothing is merged on narration.** Sam's change must pass the build gate, Claude's diff review and Lynn's
  tests. The gate exists because Sam once imported an npm package that does not exist (`mapepire`; the real one is
  `@ibm/mapepire-js`) and mocked unit tests would have passed it.
- **Merge is automatic after Lynn approves** (`PIPELINE_MERGE_PUSH=1`; `0` merges locally only). It happens in a
  throwaway worktree, never in your checkout. A conflict or rejected push blocks the issue and DMs you (the branch is
  pushed for a PR). Production deploys from main are your CI/CD.
- **Ram's tools refuse workers** (`PAPERCLIP_RUN_ID` set). Mixing Ram's key with a worker's run id is rejected by
  Paperclip as "no valid run" — that silently broke every worker's `update-status` on 2026-09-23.
- **`PAPERCLIP_API_URL` in `~/.hermes/.env` ends in `/api`**; the `paperclipai` CLI appends `/api` itself, so the
  wrappers unset it (otherwise every call 404s).
- **Slack sessions are per thread and frozen at start.** A Hermes session keeps the system prompt it started with;
  after editing SOUL.md, restart the gateway AND start a new thread (or `/new`).
- **Clarification answers** go through `ram-answer` (board-key-backed, refuses anything but a paused pipeline
  request). Ram's own bridge key cannot write to existing issues.

Things worth knowing:

- **Only enrolled issues (those with a `parentId`) are pipeline-routed.** Flat issues are never touched.
- **Human-in-the-loop points:** Claude asks for clarification; Claude can't verify the diff; Lynn blocks for a
  non-code reason; rework exceeds `PIPELINE_MAX_REWORK` (2); merge conflict; rejected push; an agent that
  keeps going silent (`PIPELINE_MAX_CHECKS`=3). Each blocks the issue and DMs you.
- **Slack is deliberately quiet:** only those events and the final result. `PIPELINE_SLACK_VERBOSE=1` adds every handoff.
- Both daemons write with a board-level workaround key over the HTTP API (upstream bug paperclipai/paperclip#13708).

### Pushing instruction changes to live agents

The repo file is the source of truth, but:
- **Aaron:** the live bundle contains a real `ADMIN_API_KEY` that the repo copy omits. Never `instructions-file:put`
  `agents/aaron.md` wholesale — patch the changed section into the live file.
- **Ram** has no instruction bundle in use: his behaviour is `~/.hermes/SOUL.md` (not in git; reproduced in spirit above).

## Approvals

Two distinct paths, on purpose:

**Routine work** (delegate a task, change a status) — Ram or a report just does it and
reports what happened. If a request is ambiguous, the instruction is to ask in Slack and
wait for the next message rather than guess — this is a prompt-level convention, not
something Paperclip enforces.

**High-stakes actions** (git push, release, hiring an agent, budget changes) — these use
Paperclip's formal approval object:

```bash
paperclipai approval create -C 0c265070-3974-497a-99ee-cf942ffe139d --api-key <Ram's standard key> \
  --type request_board_approval --requested-by-agent-id 093a44a5-da1d-421a-9708-cd1f05e6d734 \
  --payload '{"summary":"...","action":"..."}' --json
```

This is a hard boundary, not policy: an agent key gets `403: Board access required` on
`approval approve`/`approval reject` — verified directly. Only a genuine board-authenticated
identity (a human in the Paperclip web UI, or a board token in a CLI session) can decide.
Ram creating the request and a human saying "approved" in Slack does **not** let Ram
execute a high-stakes action himself; someone with board access has to actually decide it,
outside of Slack.

Check pending approvals: `paperclipai approval list -C 0c265070-3974-497a-99ee-cf942ffe139d`.

---

## Known limitations

- **The local model (Qwen3-Coder-30B-A3B) is not fully reliable for multi-step
  orchestration.** Observed failure modes: fabricating status ("completed and merged" when
  the real status was `blocked`), creating duplicate tasks instead of checking existing
  ones first, and periodically trying to *edit* `paperclip-task.mjs` instead of running it
  despite explicit instructions not to. It is markedly better at focused code-editing
  (Sam's actual patch work has been solid) than at open-ended reasoning + honest reporting
  in one chat turn. Treat Ram's narrated status claims as a starting point, not a fact,
  until verified with `paperclipai issue list`.
- **LAN exposure of the Paperclip UI from other devices has been unreliable** — loopback
  access (via SSH/VS Code port-forwarding) has been the confirmed-working path;
  `192.168.68.83:3100` has hung for the operator from another machine on the LAN. Not
  root-caused.
- **`hooks_auto_accept: true`** is enabled for the Hermes gateway so it can run shell
  commands without an interactive TTY approval. This was an explicit, informed trade-off
  (matches upstream's own recommendation for headless gateway/API-server mode) — it means
  the gateway will run any command it decides to run, with no human review of that specific
  command.
- **Two `llama-server`-looking processes may appear in `ps aux`** — one is the actual
  router (`llama-qwen.service`), the other is its own internal model-worker child process
  (`tools/server/server-models.cpp`). Only one model is ever resident in VRAM. Do not stop
  the worker process directly.

---

## Common operational commands

```bash
# Service health
systemctl status llama-qwen
paperclipai service status
hermes gateway status
journalctl --user -u hermes-gateway.service -f

# Real task status (not list-assigned)
paperclipai issue list -C 0c265070-3974-497a-99ee-cf942ffe139d --json

# Restart the gateway after editing SOUL.md, config.yaml, or .env
hermes gateway restart

# Push an updated agents/<name>.md into its live Paperclip instructions bundle
paperclipai agent instructions-file:put <agentId> --path AGENTS.md --content-file agents/<name>.md

# Manually trigger an agent's heartbeat (does not require a Paperclip-side change first)
paperclipai agent heartbeat:invoke <agentId>

# Pending approvals
paperclipai approval list -C 0c265070-3974-497a-99ee-cf942ffe139d
```

---

## Adding a new agent

1. Write `agents/<name>.md` in this repo — role, inputs, job steps, and a "Reporting back
   to Paperclip" section modeled on the existing four (state which dispositions apply to
   this role and when).
2. Create the Paperclip agent (`hermes_local`, `reportsTo` Ram's ID, `adapterConfig.model`
   set explicitly to `qwen3-coder-30b-a3b-q4-k-xl` — leaving it unset defaults to the
   literal string `"auto"`, which the server rejects).
3. Push the instructions bundle (`instructions-file:put`).
4. Create a `task_bridge` key scoped to the fleet project with
   `allowedAssigneeAgentIds` limited to the new agent's own ID, and wire it into the
   agent's `adapterConfig.env` (`PAPERCLIP_BRIDGE_API_KEY`, `PAPERCLIP_API_URL`,
   `PAPERCLIP_COMPANY_ID`, `PAPERCLIP_AGENT_ID`).
5. Add the new agent to Ram's SOUL.md roster and `allowedAssigneeAgentIds` list on Ram's
   own task-bridge key, so Ram can actually delegate to them.
