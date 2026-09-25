# Ram's commands

Ram (the Slack front door) has three commands — `ram-file`, `ram-status`, `ram-answer` — installed into
`~/.hermes/bin` together with `ram_common.py`. They exist because his model, given free-form Paperclip commands,
fabricated statuses, filed one request three times, and could not resume a paused issue.

| Command | Does | Guards |
|---|---|---|
| `ram-file --title T --request R [--thread TS] [--force]` | Files epic + request (unassigned, backlog, `SLACK_ORIGIN`) | Refuses a similar unfinished request (overlap ≥0.45 on ≥6 significant words, calibrated on the real Mapepire duplicates); refuses vague requests; reports an orphan epic if the second step fails |
| `ram-status [RSA-NN]` | What is really in flight, in plain English | Read-only; the CLI URL bug that 404'd every check is fixed |
| `ram-answer RSA-NN "answer"` | Posts the requester's answer and resumes a **paused** request at the stage it stopped | Only `blocked`, unassigned pipeline children; uses the board workaround key for two writes (comment + status) because Ram's bridge key cannot write to existing issues |

All refuse worker agents (`PAPERCLIP_RUN_ID` set). Credentials are read from `~/.hermes/.env` /
`~/.pipeline-advancer/.env`; the model never types a key.

Install: `cp ram_common.py ram-file ram-status ram-answer ~/.hermes/bin/ && chmod +x ~/.hermes/bin/ram-*`.
Tests: `python3 -m unittest test_ram_tools`.
