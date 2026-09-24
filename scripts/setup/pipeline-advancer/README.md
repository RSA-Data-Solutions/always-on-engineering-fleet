# Build plan — Pipeline Advancer

Started as a fix for a confirmed live bug (2026-09-22, verified directly against the running
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

## The pipeline (revised 2026-09-23)

```
Slack ─▶ Ram acknowledges, files epic + child (unassigned, backlog)
          │
  1 SPEC  │ Claude Supervisor: "**Claude spec review**" (enhanced request)
          │   ready              → description enriched, assigned to Sam (todo)
          │   needs-clarification → blocked, Slack question   (human answers, sets backlog → re-review)
  2 DEV   │ Sam works, sets done
          │   done               → unassigned + backlog, stage=code
  3 REVIEW│ Claude Supervisor: "**Claude code review**" against the request + the diff
          │   approve            → assigned to Lynn (todo) with Claude's TEST REQUESTS
          │   rework             → back to Sam (todo) with REWORK ITEMS      (counts as a rework)
          │   needs-human-look   → blocked, Slack-notify (e.g. no diff found)
  4 QA    │ Lynn tests, sets done or blocked
          │   done               → Aaron (todo)                              (= Lynn approves)
          │   blocked + code_bug → back to Sam (todo) with her findings      (counts as a rework)
          │   blocked otherwise  → paused, Slack-notify
  5 DEPLOY│ Aaron deploys, sets done
          │   done               → result posted to Slack in Ram's name (origin thread
          ▼                        if recorded, else the DM); issue + epic closed
```

Rework loops (Claude `rework` and Lynn `code_bug`) share one counter per issue,
capped at `PIPELINE_MAX_REWORK` (default 2); past that the issue is blocked and a
human is notified. After any rework Sam's fix goes back through the Claude code
review before Lynn sees it again.

Every transition also leaves a comment on the issue (the board's audit trail). Slack
only hears about things a human needs to act on, plus the final result;
`PIPELINE_SLACK_VERBOSE=1` adds every handoff.

**The stage lives in the issue itself.** The advancer's comments carry a
`[pipeline-stage: spec|dev|code|qa|deploy]` tag; Claude Supervisor reads the latest tag
to know which review to write and treats a review as done once its comment appears after
that tag. There is no separate stage field (the CLI can't set one) and Claude Supervisor
keeps no state for this.

### Why Claude's stages are "unassigned + backlog"

An obvious design assigns the issue to the Claude Supervisor agent while Claude works.
That fails: verified live 2026-09-23, assigning to a `process`-adapter agent wakes it, and
when the run ends without setting a disposition Paperclip auto-blocks the issue ("needs a
disposition… a board decision is required"). Claude Supervisor is advisory and never sets
a status, so every issue would block at step 1. An unassigned `backlog` issue wakes
nobody. The advancer therefore also writes over the HTTP API rather than the CLI, because
`paperclipai issue update` cannot clear an assignee.

## Enrollment: parentId, not a label

Paperclip's CLI can't attach a label to an issue, so `parentId` is the enrollment marker
(only issues with a parent are touched; flat issues are ignored). For a Slack request Ram
files two issues — the epic (records the request and where it came from) and the child
(the work item that flows through the stages; it is reassigned in place, never cloned).
Both **unassigned, status backlog**; the child's `--parent-id` is the epic's UUID. Ram
does this with the task-bridge skill (verified working with his scoped key):

```bash
cd ~/.hermes/skills/paperclip-task-bridge
node ./paperclip-task.mjs create-task --project-id b9bb008e-7771-4bc7-aad8-71e2faa3307f \
  --unassigned --status backlog --title "Feature: <name>" \
  --description "SLACK_ORIGIN: thread_ts=<id> -- Request: <verbatim>"
node ./paperclip-task.mjs create-task --project-id b9bb008e-7771-4bc7-aad8-71e2faa3307f \
  --parent-id <epic uuid> --unassigned --status backlog \
  --title "<short title>" --description "<structured request>"
```

`SLACK_ORIGIN:` (on the epic) is where the final result is posted: `thread_ts=<ts>`
threads it into the DM the request came from (the DM channel is resolved with
`conversations.open`); `channel=<id>` targets a specific channel; `SLACK_ORIGIN: none`
or nothing means an un-threaded DM to `PIPELINE_SLACK_USER_ID`. Ram is told to do all of
this by a section in `~/.hermes/SOUL.md` (see OPERATIONS.md — `SOUL.md` is outside this
repo, so the wording is reproduced there).

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
- **Agent instructions carry the pipeline contract.** `agents/sam.md` (commit with the
  issue key, read the enhanced request and rework items), `agents/lynn.md` (`done` = approve,
  run Claude's test requests, `code_bug` = send back) and `agents/aaron.md` (self-explanatory
  final comment, Ram publishes it) were updated with this design; push them with
  `instructions-file:put` (see OPERATIONS.md — never overwrite Aaron's live file wholesale, it
  holds a real key the repo copy doesn't).
- **Tests:** `python3 -m unittest scripts/setup/pipeline-advancer/test_pipeline_advancer.py`
  drives the whole pipeline (happy path, both rework loops, the cap, clarification, Slack
  routing, idempotence) through an in-memory fake Paperclip. No network or Claude needed.
- **Claude Supervisor now calls Claude for pipeline reviews** — its poll interval is 30s
  (`claude-supervisor.timer`) and it takes a lock so overlapping runs can't double-post.
- **30s poll interval** (`pipeline-advancer.timer`) matches Paperclip's own per-agent
  heartbeat, so a finished stage reaches the next agent within ~30s. Don't tighten it
  further (racing the agents' own heartbeat buys nothing); loosening it only adds latency.
