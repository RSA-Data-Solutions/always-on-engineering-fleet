#!/usr/bin/env python3
"""Pipeline Advancer daemon.

Fixes the "tasks get stuck at done" problem: today, when Sam/Lynn/Aaron
finish a Paperclip issue and set its disposition, nothing hands the issue to
the next role. This daemon watches issues that are *enrolled* in the
dev -> QA -> deploy -> review -> close pipeline and does that handoff itself,
posting a board comment and a Slack message at each transition.

Enrollment convention (deliberate — no Paperclip CLI support for issue
labels, see README.md): an issue is "in the pipeline" if it has a non-null
`parentId`. Ram enrolls a task by creating a parent "epic" issue (unassigned,
status backlog, one per feature) and creating the actual dev work as a child
of it, assigned to Sam. Investigation-only, research, and self-improvement
issues that Ram creates flat (no parent) are never touched by this daemon.

Stage map (inferred from current assignee + status, not a separate field):

    Sam (engineer)  done    -> reassign to Lynn (qa),    status=todo
    Lynn (qa)       done    -> reassign to Aaron (devops), status=todo
    Lynn/Aaron/Sam  blocked -> no reassignment; Slack-notify once, pipeline pauses
    Aaron (devops)  done    -> status=in_review (Claude Supervisor's existing
                                company-wide poller picks this up on its own)
    in_review + a Claude Supervisor comment not yet acted on:
        verdict agree              -> status=done (final close)
        verdict disagree/needs-look -> no status change; Slack-notify only
                                        (Claude Supervisor already filed a
                                        board approval for this case)

Auto-close-on-agree and "same channel Ram already talks in" (a Slack DM to
the one allowed human user) were both explicit product decisions, not
guesses — see README.md's "Design decisions" section before changing either.

Modeled directly on claude_supervisor.py in the sibling directory: same
run-scoped-key-for-reads / board-key-for-writes split (working around the
same upstream Paperclip bug, paperclipai/paperclip#13708), same state-file
de-dup pattern, same systemd-timer-driven `agent heartbeat:invoke` trigger
instead of a long-lived process. Read that file's module docstring first if
anything here is confusing — this one assumes it.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time
import traceback
import urllib.request

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

STATE_FILE = pathlib.Path(
    os.environ.get(
        "PIPELINE_ADVANCER_STATE",
        str(pathlib.Path.home() / ".pipeline-advancer" / "state.json"),
    )
)

ENV_FILE = pathlib.Path(
    os.environ.get("PIPELINE_ADVANCER_ENV_FILE", str(pathlib.Path.home() / ".pipeline-advancer" / ".env"))
)

# Real, confirmed agent ids for this company (paperclipai agent list,
# 2026-09-23) — override via env if the fleet's org chart ever changes.
SAM_ID = os.environ.get("PIPELINE_SAM_AGENT_ID", "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0")
LYNN_ID = os.environ.get("PIPELINE_LYNN_AGENT_ID", "d053dfe0-dbd6-45fd-8069-32b51a00580e")
AARON_ID = os.environ.get("PIPELINE_AARON_AGENT_ID", "a02a6b9e-4d44-4f46-b373-83c15e6309c0")
RAM_ID = os.environ.get("PIPELINE_RAM_AGENT_ID", "093a44a5-da1d-421a-9708-cd1f05e6d734")

STAGE_NAME = {SAM_ID: "dev (Sam)", LYNN_ID: "QA (Lynn)", AARON_ID: "devops (Aaron)"}


def load_env_file():
    """Read KEY=VALUE lines from ENV_FILE into a dict, ignoring comments/blank
    lines. Not injected into os.environ — read on demand, same reasoning as
    claude_supervisor.py's board_workaround_key(): a couple of these values
    (the board workaround key) are not sourced by Paperclip's per-run
    injection and must come from disk every call."""
    if not ENV_FILE.exists():
        raise RuntimeError(f"{ENV_FILE} not found")
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def board_workaround_key():
    """Same upstream bug, same workaround as claude_supervisor.py's function
    of the same name: paperclipai/paperclip#13708 — a scoped-less heartbeat
    run's own JWT 403s on any issue write. Revert to the run-scoped
    PAPERCLIP_API_KEY for writes once #13708 ships; don't leave this in place
    past that. Can point at the SAME workaround key claude-supervisor already
    uses (one board-level key covers both), or a separate one — see
    README.md for the trade-off."""
    env = load_env_file()
    key = env.get("PAPERCLIP_BOARD_KEY_WORKAROUND")
    if not key:
        raise RuntimeError(f"PAPERCLIP_BOARD_KEY_WORKAROUND not set in {ENV_FILE}")
    return key


def slack_config():
    env = load_env_file()
    token = env.get("SLACK_BOT_TOKEN")
    user_id = env.get("PIPELINE_SLACK_USER_ID")
    if not token or not user_id:
        raise RuntimeError(f"SLACK_BOT_TOKEN / PIPELINE_SLACK_USER_ID not set in {ENV_FILE}")
    return token, user_id


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"advanced": {}, "blocked_notified": {}, "review_acted": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def paperclip(*args, api_key=None):
    """Run the paperclipai CLI and return parsed JSON. api_key defaults to
    the run-scoped read key Paperclip injects; pass board_workaround_key()
    explicitly for any mutating call (comment/update)."""
    key = api_key or os.environ["PAPERCLIP_API_KEY"]
    cmd = ["paperclipai", *args, "--api-key", key]
    run_id = os.environ.get("PAPERCLIP_RUN_ID")
    if run_id:
        cmd += ["--run-id", run_id]
    cmd += ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"paperclipai {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def list_pipeline_candidates(company_id):
    """One list call per status of interest — the CLI's --status filter is a
    single value, not a set (confirmed against doc/CLI.md via claude_supervisor.py's
    same pattern). done/in_review/blocked are the only statuses this daemon
    acts on; todo/in_progress/backlog/cancelled are left alone."""
    issues = []
    for status in ("done", "in_review", "blocked"):
        issues.extend(paperclip("issue", "list", "--company-id", company_id, "--status", status))
    return [i for i in issues if i.get("parentId")]


def list_issue_comments(issue_id):
    return paperclip("issue", "comments", issue_id)


def update_issue(issue_id, **fields):
    """Mutating PATCH via the board workaround key. fields map directly to
    `paperclipai issue update` flags, e.g. status='todo', assignee_agent_id=X,
    comment='...'."""
    args = ["issue", "update", issue_id]
    flag_map = {
        "status": "--status",
        "assignee_agent_id": "--assignee-agent-id",
        "comment": "--comment",
    }
    for field, flag in flag_map.items():
        if field in fields and fields[field] is not None:
            args += [flag, fields[field]]
    return paperclip(*args, api_key=board_workaround_key())


def post_slack(text):
    token, user_id = slack_config()
    body = json.dumps({"channel": user_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {parsed.get('error')}")
    return parsed


def parse_verdict(review_text):
    """Same parsing logic as claude_supervisor.py's parse_verdict() — kept as
    a separate copy rather than a shared import so this script has no
    dependency on the sibling directory being present at runtime."""
    for line in review_text.splitlines():
        line = line.strip().lower()
        if line.startswith("1. verdict:") or line.startswith("verdict:"):
            for v in ("disagree", "needs-human-look", "agree"):
                if v in line:
                    return v
    return "needs-human-look"


def dedup_key(issue):
    return f"{issue['id']}:{issue.get('status')}:{issue.get('statusVersion')}"


def handle_done(issue, state, dry_run):
    key = issue.get("identifier") or issue["id"]
    assignee = issue.get("assigneeAgentId")
    ddkey = dedup_key(issue)
    if state["advanced"].get(issue["id"]) == ddkey:
        return False

    if assignee == SAM_ID:
        next_id, next_name, next_status = LYNN_ID, "QA (Lynn)", "todo"
        note = "dev complete, handing off to QA (Lynn)"
        emoji = "\U0001f527→\U0001f9ea"
    elif assignee == LYNN_ID:
        next_id, next_name, next_status = AARON_ID, "devops (Aaron)", "todo"
        note = "QA passed, handing off to devops (Aaron) for deploy"
        emoji = "\U0001f9ea→\U0001f680"
    elif assignee == AARON_ID:
        next_id, next_name, next_status = None, None, "in_review"
        note = "deployed, sending to Claude Supervisor for verification"
        emoji = "\U0001f680→\U0001f50e"
    else:
        return False  # done, but not one of the three pipeline roles — ignore

    print(f"[{datetime.datetime.now().isoformat()}] {key}: done at {STAGE_NAME.get(assignee, assignee)} -> {note}")
    if dry_run:
        return True

    update_issue(
        issue["id"],
        status=next_status,
        assignee_agent_id=next_id,
        comment=f"Pipeline: {note}.",
    )
    post_slack(f"{emoji} {key}: {note}. ({issue.get('title', '')})")
    state["advanced"][issue["id"]] = ddkey
    return True


def handle_blocked(issue, state, dry_run):
    key = issue.get("identifier") or issue["id"]
    assignee = issue.get("assigneeAgentId")
    if assignee not in (SAM_ID, LYNN_ID, AARON_ID):
        return False
    ddkey = dedup_key(issue)
    if state["blocked_notified"].get(issue["id"]) == ddkey:
        return False

    print(f"[{datetime.datetime.now().isoformat()}] {key}: blocked at {STAGE_NAME.get(assignee, assignee)}")
    if dry_run:
        return True

    comments = list_issue_comments(issue["id"])
    last_comment = comments[-1]["body"] if comments else "(no comment)"
    post_slack(
        f"\U0001f6d1 {key} is BLOCKED at {STAGE_NAME.get(assignee, assignee)} and needs a human look.\n"
        f"({issue.get('title', '')})\nLatest note: {last_comment[:300]}"
    )
    state["blocked_notified"][issue["id"]] = ddkey
    return True


def handle_in_review(issue, state, dry_run):
    key = issue.get("identifier") or issue["id"]
    comments = list_issue_comments(issue["id"])
    supervisor_comments = [c for c in comments if "**Claude Supervisor review**" in (c.get("body") or "")]
    if not supervisor_comments:
        return False  # Claude Supervisor hasn't reviewed this yet
    latest = supervisor_comments[-1]
    comment_id = latest.get("id")
    if state["review_acted"].get(issue["id"]) == comment_id:
        return False  # already acted on this exact review

    verdict = parse_verdict(latest.get("body", ""))
    print(f"[{datetime.datetime.now().isoformat()}] {key}: acting on Claude Supervisor verdict={verdict}")
    if dry_run:
        return True

    if verdict == "agree":
        update_issue(
            issue["id"],
            status="done",
            comment="Pipeline: Claude Supervisor agreed — closing. Confirmed via the automated fleet pipeline on Ram's behalf.",
        )
        post_slack(f"✅ {key} closed — full pipeline passed (dev → QA → deploy → review). ({issue.get('title', '')})")
    else:
        post_slack(
            f"⚠️ {key} needs your review — Claude Supervisor said '{verdict}'. "
            f"Check `paperclipai approval list` for the escalation. ({issue.get('title', '')})"
        )
    state["review_acted"][issue["id"]] = comment_id
    return True


def run_once(args, state):
    candidates = list_pipeline_candidates(args.company_id)
    acted = 0
    for issue in candidates:
        status = issue.get("status")
        try:
            if status == "done":
                acted += handle_done(issue, state, args.dry_run)
            elif status == "blocked":
                acted += handle_blocked(issue, state, args.dry_run)
            elif status == "in_review":
                acted += handle_in_review(issue, state, args.dry_run)
        except Exception as e:
            print(f"error handling {issue.get('identifier') or issue.get('id')}: {e}", file=sys.stderr)
    if not args.dry_run:
        save_state(state)
    print(f"done: {len(candidates)} pipeline-enrolled candidate(s), {acted} action(s) taken")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company-id", dest="company_id", default=os.environ.get("PAPERCLIP_COMPANY_ID"))
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would happen but never call paperclipai write endpoints or Slack",
    )
    args = p.parse_args()

    if not args.company_id:
        p.error("missing required config: company_id (env PAPERCLIP_COMPANY_ID or --company-id)")

    state = load_state()
    if args.once:
        run_once(args, state)
        return
    # Not expected to be used in production (systemd timer drives --once the
    # same way claude-supervisor.timer does) but kept for local testing.
    while True:
        try:
            run_once(args, state)
        except Exception as e:
            print(f"error during poll cycle: {e}", file=sys.stderr)
        time.sleep(300)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("FATAL:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
