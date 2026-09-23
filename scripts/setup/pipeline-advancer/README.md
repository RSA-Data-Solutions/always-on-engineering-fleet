# Build plan — Pipeline Advancer

Fixes a confirmed live bug (2026-09-22, verified directly against the running
`sashi-llm` Paperclip instance): when Sam, Lynn, or Aaron finish an issue and
set a disposition, nothing hands the work to the next role. Six real issues
(RSA-4, 8, 17, 18, 19, 20) were sitting at `done`, assigned to Sam, with no
QA, no deploy, no review, no close — exactly the "tasks get stuck" symptom
this was built to fix.

This directory is a direct sibling of `../claude-supervisor/` and copies its
proven shape on purpose: a standalone script driven by a systemd timer that
triggers one Paperclip heartbeat per interval, reads with the run-injected
key, writes with a board-level workaround key (upstream bug
paperclipai/paperclip#13708 — see `pipeline_advancer.py`'s docstrings, not
repeated here). Read `../claude-supervisor/README.md` first if any of that
is unfamiliar.

---

## Design decisions (already made — don't relitigate without a reason)

These three were explicit product choices, made 2026-09-22:

1. **Scope: label-gated, not everything.** Only issues enrolled in the
   pipeline (see "Enrollment" below) auto-advance. Investigation/research/
   self-improvement issues Ram creates flat are left alone — RSA-19/20 (both
   "Investigate ..." tasks) are a real example of work that should NOT
   cascade into a deploy pipeline.
2. **Auto-close on agree.** Once Aaron deploys and Claude Supervisor's
   advisory review comes back `agree`, the daemon closes the issue itself
   (status -> `done`) rather than waiting for Ram or a human to say so. This
   matches OPERATIONS.md's existing routine-vs-high-stakes split: routine
   work just happens, only genuinely high-stakes actions need board
   approval. A non-`agree` verdict already gets escalated to a board
   approval by `claude_supervisor.py` — that path is untouched, and this
   daemon does NOT auto-close on disagree/needs-human-look.
3. **Slack destination: the existing Ram conversation.** Status messages go
   to the one Slack user id Ram already talks to
   (`~/.hermes/.env`'s `SLACK_ALLOWED_USERS`, single value on this install),
   via `chat.postMessage` with `channel=<that user id>` — opens/reuses the
   same DM rather than posting to a separate ops channel.

## Enrollment: parentId, not a label

Paperclip's CLI has `issue label:list/create/delete` but **no command to
attach a label to an issue** (confirmed against `paperclipai issue --help`
directly, 2026-09-22) — so a label-based convention isn't actually buildable
from the CLI today. `parentId` already exists on every issue for exactly
this kind of grouping, so that's the enrollment marker instead:

1. Ram creates a parent "epic" issue for the feature — unassigned,
   `status=backlog`, no special fields:
   ```bash
   paperclipai issue create --company-id 0c265070-3974-497a-99ee-cf942ffe139d \
     --title "Feature: <name>" --status backlog --api-key <Ram's task_bridge key> --json
   ```
2. Ram creates the actual dev task as its **child**, assigned to Sam:
   ```bash
   paperclipai issue create --company-id 0c265070-3974-497a-99ee-cf942ffe139d \
     --title "<dev task title>" --parent-id <epic issue id> \
     --assignee-agent-id ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0 --status todo \
     --api-key <Ram's task_bridge key> --json
   ```
   (`paperclip-task.mjs create-task` doesn't expose `--parent-id` today —
   use the raw `paperclipai issue create` CLI for enrolled work until that's
   added, same as this bullet shows.)

The child issue is the one that flows through the pipeline — Sam, Lynn, and
Aaron all work the *same issue*, reassigned in place; no new issues are
spawned per stage. Only the initial epic-plus-child creation is manual (by
Ram); everything after that is this daemon.

## Stage map

```
Sam done     -> reassign Lynn,  status=todo         ("dev complete, handing off to QA")
Lynn done    -> reassign Aaron, status=todo         ("QA passed, handing off to devops")
Lynn/Aaron/
Sam blocked  -> no reassignment; Slack-notify once, pipeline pauses for a human
Aaron done   -> status=in_review                    (claude-supervisor's existing
                                                      company-wide poller picks it up
                                                      on its own timer — no new wiring)
in_review +
Claude Supervisor
comment posted:
  verdict agree              -> status=done (closed)
  verdict disagree/needs-look -> Slack-notify only (claude_supervisor.py already
                                  filed the board approval; this daemon doesn't
                                  duplicate that)
```

Every transition also gets a comment on the issue itself (visible on the
Paperclip board) and a Slack message to Ram's conversation, so the same
event is visible in both places — this is the "communicated to board and
Slack at each stage" part of the original ask.

## Manual setup (you do this — needs board-level Paperclip access)

1. **Create the Pipeline Advancer agent identity**, `process` adapter type,
   same shape as Claude Supervisor's (`paperclipai agent get
   7e92a434-b670-4c72-8fbf-78ecbff0f52b --json` shows the reference shape):
   ```bash
   paperclipai agent create --company-id 0c265070-3974-497a-99ee-cf942ffe139d --payload-json '{
     "name": "Pipeline Advancer",
     "title": "Handoff Automation",
     "reportsTo": "093a44a5-da1d-421a-9708-cd1f05e6d734",
     "adapterType": "process",
     "adapterConfig": {
       "command": "/usr/bin/env",
       "args": ["python3", "/home/sashi/.pipeline-advancer/pipeline_advancer.py", "--once"],
       "cwd": "/home/sashi/.pipeline-advancer",
       "timeoutSec": 120
     },
     "permissions": { "canAssignTasks": true, "canCreateAgents": false, "canCreateSkills": false }
   }' --json
   ```
   `canAssignTasks: true` (unlike Claude Supervisor's `false`) because this
   daemon's whole job is reassigning issues — doesn't matter today since
   writes route through the board workaround key regardless, but will matter
   once bug #13708 ships and writes move back to the agent's own scoped key.
2. **Mint its API key** (used only by `verify.sh` for manual testing — see
   the comment on `PAPERCLIP_API_KEY` in the env template):
   ```bash
   paperclipai token agent create --company-id 0c265070-3974-497a-99ee-cf942ffe139d \
     --agent <new-agent-id> --name pipeline-advancer-self
   ```
3. **Get (or reuse) a board-level workaround key** for the mutating calls.
   If `~/.claude-supervisor/.env`'s `PAPERCLIP_BOARD_KEY_WORKAROUND` already
   exists, you can point this daemon's `.env` at the same value — one board
   key, two daemons, both purely additive (comments + status changes on
   different issue sets in practice). Mint a separate one instead if you'd
   rather keep independent revocation / audit trails.
4. **Get the Slack values**: `SLACK_BOT_TOKEN` from `~/.hermes/.env` (same
   bot Hermes already uses — copy the value, don't move/delete it from
   there), and the single value from `~/.hermes/.env`'s
   `SLACK_ALLOWED_USERS` for `PIPELINE_SLACK_USER_ID`.

## Deploy (on this host, as `sashi`)

```bash
cd scripts/setup/pipeline-advancer
./install.sh <pipeline-advancer-agent-id-from-step-1>
# edit ~/.pipeline-advancer/.env with the values from "Manual setup" above
./verify.sh
# if the dry run looks right:
systemctl --user enable --now pipeline-advancer.timer
journalctl --user -u pipeline-advancer -f
```

`install.sh` is idempotent — safe to re-run after pulling an updated
`pipeline_advancer.py` from this repo. It never overwrites an existing
`.env` and never starts the timer on its own.

## Known limitations

- **Reassignment authority runs through the board workaround key, not a
  scoped agent key** — same bug (#13708), same reasoning as
  claude-supervisor. Revert both once it ships.
- **No CLI support for attaching labels to issues**, which is why enrollment
  uses `parentId` instead of a label as originally sketched. If Paperclip
  adds label-attachment to the CLI later, switching the enrollment check in
  `list_pipeline_candidates()`/the `handle_*` functions from "has a
  parentId" to "has the pipeline label" is a small, contained change.
- **Single shared Paperclip project**, like claude-supervisor — this daemon
  watches `done`/`in_review`/`blocked` issues across the whole company, not
  scoped to one project, since the fleet only runs one today.
- **Sam/Lynn/Aaron's own agent instructions are unchanged.** They already
  just set `done`/`blocked`/`in_review` on their own issue and stop — this
  daemon does the rest externally. No behavioral change needed on their
  side, only documentation (see `OPERATIONS.md` and the "Reporting back to
  Paperclip" sections in `agents/*.md`).
- **90s poll interval** (`pipeline-advancer.timer`) is faster than
  claude-supervisor's 300s because a stuck handoff is the whole problem
  being solved here — don't loosen it without a reason, and don't tighten it
  much further either (Paperclip's own per-agent heartbeat is ~30s; racing
  much faster than that buys nothing).
