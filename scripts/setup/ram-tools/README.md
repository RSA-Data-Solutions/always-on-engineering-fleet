# Ram's commands

Ram has four commands — `ram-file`, `ram-status`, `ram-answer`, `ram-reply` — installed into `~/.hermes/bin`
together with `ram_common.py`. They exist because his model, given free-form Paperclip commands, fabricated
statuses, filed one request three times, and could not resume a paused issue.

Since 2026-09-30 there is no pipeline advancer: every request is one parent issue owned by Ram, and Ram (in
Paperclip) routes it one child issue per stage — see `agents/ram.md`. Slack Ram follows `~/.hermes/SOUL.md`.

| Command | Used by | Does | Guards |
|---|---|---|---|
| `ram-file --title T --request R [--thread TS] [--force]` | Slack Ram | Files the request as one issue assigned to Ram (`ORIGIN: slack thread_ts=…` + request), which wakes Ram in Paperclip | Refuses a similar unfinished request (overlap ≥0.45 on ≥6 significant words, calibrated on the real Mapepire duplicates); refuses vague requests |
| `ram-status [RSA-NN]` | Slack Ram | What is really in flight: each request and its current stage, in plain English | Read-only |
| `ram-answer RSA-NN "answer"` | Slack Ram | Records the requester's answer on the request and wakes Ram to continue | Unfinished requests only; a stage issue resolves to its request |
| `ram-reply RSA-NN "message"` | Paperclip Ram | Posts in the request's Slack thread (DM to `SLACK_ALLOWED_USERS`) and records it on the request | Slack only when `ORIGIN: slack` |
| `ram-paperclipai <paperclipai args>` | Both | Runs the `paperclipai` CLI as Ram: the standard key from Slack, the run's own key inside Ram's Paperclip runs (which can assign tasks) | Refuses any other agent's run |

`SOUL.md` here is the versioned copy of `~/.hermes/SOUL.md` — Ram's Slack persona and command rules (no secrets).
Edit it here, install it, then restart the gateway and start a new Slack thread (sessions keep the prompt they
started with).

All refuse worker agents (inside a Paperclip run as anyone but Ram). Credentials are read from `~/.hermes/.env`
(`PAPERCLIP_RAM_STANDARD_KEY`, `SLACK_BOT_TOKEN`); the model never types a key.

Install:

```bash
cp ram_common.py ram-file ram-status ram-answer ram-reply ram-paperclipai ~/.hermes/bin/ && chmod +x ~/.hermes/bin/ram-*
cp SOUL.md ~/.hermes/SOUL.md && systemctl --user restart hermes-gateway.service
```

Tests: `python3 -m unittest test_ram_tools`.
