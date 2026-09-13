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
| Ram's task-bridge key (`task_bridge`, scoped to the fleet project, can assign to all 4 reports) | Ram's delegation (`create-task`, `comment`, `update-status`) | Ram's Paperclip `adapterConfig.env.PAPERCLIP_BRIDGE_API_KEY`, and literally inlined in `~/.hermes/SOUL.md` |
| Ram's standard key (broad read, cannot approve/reject) | `paperclipai issue list` for real status checks | Ram's `adapterConfig.env.PAPERCLIP_API_KEY`, inlined in `~/.hermes/SOUL.md` |
| Each of Aaron/Dhira/Lynn/Sam's own `task_bridge` key (scoped to themselves only) | Self-reporting disposition (`update-status`, `comment`) on their own assigned issues | Each agent's own `adapterConfig.env.PAPERCLIP_BRIDGE_API_KEY` |
| `API_SERVER_KEY` | Gateway's own HTTP API (port 8642) | `~/.hermes/.env` |
| Slack `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Gateway's Slack connection | `~/.hermes/.env` |

Ram's SOUL.md contains inlined literal key values rather than shell-variable references
on purpose — the model was not reliably expanding `$VAR` references when constructing
terminal commands. This is a real trade-off: SOUL.md is more sensitive as a result. It is
not committed to Git (`~/.hermes/` is outside this repo).

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
   see Known limitations below.

---

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
