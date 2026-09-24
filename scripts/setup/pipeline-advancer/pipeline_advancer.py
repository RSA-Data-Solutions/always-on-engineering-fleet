#!/usr/bin/env python3
"""Pipeline Advancer daemon.

Drives an *enrolled* Paperclip issue through the fleet's delivery pipeline and
is the ONLY component that routes issues between stages. Every other party
(Sam, Lynn, Aaron, Claude Supervisor) just does its stage and reports; this
daemon reads the report and does the handoff, posting a comment on the issue
at each transition.

Enrollment (unchanged): an issue is "in the pipeline" if it has a non-null
`parentId`. For a Slack request Ram creates a parent "epic" (unassigned,
backlog — its description carries the Slack origin, see SLACK_ORIGIN below)
and one child issue (unassigned, backlog — its description is the request).
Flat issues (no parent) are never touched.

The pipeline:

    Slack -> Ram (acknowledges, files epic + child)
      1. SPEC     child sits unassigned/backlog. Claude Supervisor writes a
                  "**Claude spec review**" comment (enhanced request).
                  ready -> description enriched, assigned to Sam (todo)
                  needs-clarification -> blocked, Slack-notify
      2. DEV      Sam (todo) works it, sets done.
                  done -> unassigned/backlog, stage=code
      3. REVIEW   Claude Supervisor writes "**Claude code review**".
                  approve -> assigned to Lynn (todo), test requests in comment
                  rework  -> back to Sam (todo) with the rework items
                  needs-human-look -> blocked, Slack-notify
      4. QA       Lynn (todo) tests.
                  done -> Aaron (todo)
                  blocked + code_bug -> back to Sam (rework)
                  blocked otherwise  -> pause, Slack-notify
      5. DEPLOY   Aaron (todo) deploys, sets done.
                  done -> result posted to Slack in Ram's name (the origin
                          thread if known, else the DM), issue + epic closed,
                          assignee set to Ram.

Why Claude's stages are "unassigned + backlog" instead of "assigned to the
Claude Supervisor agent": verified live 2026-09-23 — assigning an issue to a
process-adapter agent wakes it, and when the run ends without setting a
disposition Paperclip auto-blocks the issue ("needs a disposition"). Claude
Supervisor is advisory and never sets a status, so assignment would block
every issue at step 1. An unassigned backlog issue wakes nobody; the stage
is carried by a `[pipeline-stage: X]` tag in this daemon's own comments, and
claude_supervisor.py reads the same tag to know which review to write.

Rework loops (Lynn code_bug, Claude "rework") share one counter per issue,
capped at PIPELINE_MAX_REWORK (default 2); past that the issue is blocked and
a human is notified instead of looping forever.

Writes use the board workaround key over the HTTP API (not the CLI): the CLI
cannot clear an assignee, and the run-scoped key 403s on issue writes due to
upstream bug paperclipai/paperclip#13708 — revert to the scoped key once it
ships. Reads use the run-injected key. See claude_supervisor.py's
board_workaround_key() docstring for the full story.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import traceback
import urllib.error
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

API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api")

# Real, confirmed agent ids for this company (paperclipai agent list,
# 2026-09-23) — override via env if the fleet's org chart ever changes.
SAM_ID = os.environ.get("PIPELINE_SAM_AGENT_ID", "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0")
LYNN_ID = os.environ.get("PIPELINE_LYNN_AGENT_ID", "d053dfe0-dbd6-45fd-8069-32b51a00580e")
AARON_ID = os.environ.get("PIPELINE_AARON_AGENT_ID", "a02a6b9e-4d44-4f46-b373-83c15e6309c0")
RAM_ID = os.environ.get("PIPELINE_RAM_AGENT_ID", "093a44a5-da1d-421a-9708-cd1f05e6d734")

STAGE_NAME = {SAM_ID: "dev (Sam)", LYNN_ID: "QA (Lynn)", AARON_ID: "devops (Aaron)"}
AGENT_NAME = {SAM_ID: "Sam", LYNN_ID: "Lynn", AARON_ID: "Aaron", RAM_ID: "Ram"}



def cfg(name, default=""):
    """Setting from the process env, else from ~/.pipeline-advancer/.env —
    Paperclip's process adapter does not source that file, so optional
    tunables must be read from disk too or they would silently never apply."""
    if name in os.environ:
        return os.environ[name]
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return default


MAX_REWORK = int(cfg("PIPELINE_MAX_REWORK", "2"))

# Slack: only "blocked / needs a human" and the final result are posted by
# default. Set PIPELINE_SLACK_VERBOSE=1 to also post every handoff.
SLACK_VERBOSE = cfg("PIPELINE_SLACK_VERBOSE").lower() in ("1", "true", "yes")

# Markers shared with claude_supervisor.py (kept as separate copies on
# purpose — no runtime dependency on the sibling directory).
SPEC_MARK = "**Claude spec review**"
CODE_MARK = "**Claude code review**"
STAGE_TAG_RE = re.compile(r"\[pipeline-stage:\s*([a-z-]+)\]", re.IGNORECASE)
ENHANCED_HEADER = "## Enhanced request (Claude spec review)"
# Ram records where the request came from on the epic, e.g.
#   SLACK_ORIGIN: thread_ts=1790059229.120989
#   SLACK_ORIGIN: channel=C0123ABC thread_ts=1790059229.120989
# Hermes only shows Ram the thread timestamp for a DM (not the D... channel id),
# so `channel` is optional: with none, the result goes to the configured user's
# DM (resolved via conversations.open) and into `thread_ts` if given.
SLACK_ORIGIN_RE = re.compile(
    r"SLACK_ORIGIN:\s*(?:channel=([A-Z0-9]+))?\s*(?:thread_ts=([0-9]+\.[0-9]+))?", re.IGNORECASE
)

_UNSET = object()  # "leave this field alone" vs None == "clear it"


def now():
    return datetime.datetime.now().isoformat()


def load_env_file():
    """Read KEY=VALUE lines from ENV_FILE into a dict, ignoring comments/blank
    lines. Not injected into os.environ — read on demand: a couple of these
    values (the board workaround key) are not sourced by Paperclip's per-run
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
    of the same name: paperclipai/paperclip#13708. Revert to the run-scoped
    PAPERCLIP_API_KEY for writes once #13708 ships; don't leave this in place
    past that."""
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
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    for key in ("advanced", "blocked_notified", "review_acted", "rework", "published"):
        state.setdefault(key, {})
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def paperclip(*args):
    """Run the paperclipai CLI (read-only use) with the run-scoped key Paperclip
    injects, and return parsed JSON."""
    cmd = ["paperclipai", *args, "--api-key", os.environ["PAPERCLIP_API_KEY"]]
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
    single value. backlog (Claude stages), done (handoffs), blocked and
    in_review (human-look notifications) are the only statuses acted on; todo
    and in_progress mean an agent is working and are left alone."""
    issues = []
    for status in ("backlog", "done", "blocked", "in_review"):
        issues.extend(paperclip("issue", "list", "--company-id", company_id, "--status", status))
    return [i for i in issues if i.get("parentId")]


def get_issue(issue_id):
    return paperclip("issue", "get", issue_id)


def list_issue_comments(issue_id):
    comments = paperclip("issue", "comments", issue_id)
    return sorted(comments, key=lambda c: c.get("createdAt") or "")


# Paperclip rejects `status=blocked` (422 "Entering blocked requires unresolved
# blockers, a pending interaction/approval, or unblockDescriptor") unless it is
# told who unblocks it. Every block this daemon sets is waiting on a human.
UNBLOCK_DESCRIPTOR = {
    "owner": "board",
    "action": "Read the latest pipeline comment and Slack message, then set the issue back to "
    "backlog (spec/code review) or todo (agent stage) to resume.",
}


def http_patch(issue_id, body):
    """PATCH /api/issues/{id} with the board workaround key."""
    req = urllib.request.Request(
        f"{API_BASE}/issues/{issue_id}",
        data=json.dumps(body).encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {board_workaround_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"PATCH issue {issue_id} failed: {e.code} {e.read().decode()[:300]}")


def update_issue(issue_id, status=_UNSET, assignee=_UNSET, comment=_UNSET, description=_UNSET):
    """Update an issue. `assignee=None` clears the assignee (the CLI can't
    express that, hence the HTTP API)."""
    body = {}
    if status is not _UNSET:
        body["status"] = status
        if status == "blocked":
            body["unblockDescriptor"] = UNBLOCK_DESCRIPTOR
    if assignee is not _UNSET:
        body["assigneeAgentId"] = assignee
    if comment is not _UNSET:
        body["comment"] = comment
    if description is not _UNSET:
        body["description"] = description
    return http_patch(issue_id, body)


def slack_api(method, token, payload):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {parsed.get('error')}")
    return parsed


def post_slack(text, channel=None, thread_ts=None):
    """Post as the Slack bot (Ram's identity). No channel -> the configured
    user's DM; a thread_ts needs the real DM channel id, so resolve it first
    and fall back to an un-threaded DM post if that isn't permitted."""
    token, user_id = slack_config()
    if thread_ts and not channel:
        try:
            channel = slack_api("conversations.open", token, {"users": user_id})["channel"]["id"]
        except Exception as e:
            print(f"  could not resolve DM channel for threading ({e}); posting un-threaded", file=sys.stderr)
            thread_ts = None
    payload = {"channel": channel or user_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return slack_api("chat.postMessage", token, payload)


def notify(text):
    """Handoff chatter — quiet unless PIPELINE_SLACK_VERBOSE is set."""
    if SLACK_VERBOSE:
        post_slack(text)


# ---------------------------------------------------------------- parsing


def parse_field(text, name):
    """Value of a `N. NAME: value` / `NAME: value` line, lowercased, or None."""
    for line in text.splitlines():
        m = re.match(rf"^\s*(?:\d+\.\s*)?\**{re.escape(name)}\**\s*:\s*(.*)$", line, re.IGNORECASE)
        if m:
            return m.group(1).strip().lower()
    return None


def parse_section(text, name, next_names=()):
    """Text after a `NAME:` heading line up to the next heading in
    `next_names` (or the end). Returns '' if the heading is absent."""
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if re.match(rf"^\s*(?:\d+\.\s*)?\**{re.escape(name)}\**\s*:", line, re.IGNORECASE):
            start = idx
            break
    if start is None:
        return ""
    first = re.sub(rf"^\s*(?:\d+\.\s*)?\**{re.escape(name)}\**\s*:\s*", "", lines[start], flags=re.IGNORECASE)
    out = [first] if first.strip() else []
    stop = "|".join(re.escape(n) for n in next_names)
    for line in lines[start + 1 :]:
        if stop and re.match(rf"^\s*(?:\d+\.\s*)?\**(?:{stop})\**\s*:", line, re.IGNORECASE):
            break
        out.append(line)
    return "\n".join(out).strip()


def pick_verdict(text, allowed, default):
    value = parse_field(text, "verdict") or ""
    for v in allowed:
        if v in value:
            return v
    return default


def current_stage(comments):
    """(stage, index-of-the-comment-that-set-it). Default is 'spec' — a fresh
    child issue has no pipeline comment yet and needs the spec review."""
    stage, idx = "spec", -1
    for i, c in enumerate(comments):
        m = STAGE_TAG_RE.search(c.get("body") or "")
        if m:
            stage, idx = m.group(1).lower(), i
    return stage, idx


def pending_claude_review(comments, stage, stage_idx):
    """Latest Claude review comment for `stage` posted after the stage was
    entered, or None."""
    mark = SPEC_MARK if stage == "spec" else CODE_MARK
    found = None
    for i, c in enumerate(comments):
        if i > stage_idx and mark in (c.get("body") or ""):
            found = c
    return found


def last_comment_by(comments, agent_id):
    mine = [c for c in comments if c.get("authorAgentId") == agent_id]
    return mine[-1] if mine else None


def tag(stage):
    return f"[pipeline-stage: {stage}]"


def dedup_key(issue):
    return f"{issue['id']}:{issue.get('status')}:{issue.get('statusVersion')}"


def label(issue):
    return issue.get("identifier") or issue["id"]


def clip(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# --------------------------------------------------------------- handlers


def send_to_sam(issue, comment, state, rework=False):
    """Put the issue in Sam's queue. Returns False (and blocks the issue)
    when a rework would exceed the cap."""
    if rework:
        n = state["rework"].get(issue["id"], 0) + 1
        if n > MAX_REWORK:
            update_issue(
                issue["id"],
                status="blocked",
                assignee=None,
                comment=f"Pipeline: rework limit ({MAX_REWORK}) reached — pausing for a human. {tag('dev')}\n\n{comment}",
            )
            post_slack(
                f"\U0001f6d1 {label(issue)} bounced back to dev more than {MAX_REWORK} times and is paused "
                f"for a human look. ({issue.get('title', '')})"
            )
            return False
        state["rework"][issue["id"]] = n
        comment = f"Pipeline: rework {n}/{MAX_REWORK}.\n\n{comment}"
    update_issue(issue["id"], status="todo", assignee=SAM_ID, comment=f"{comment}\n\n{tag('dev')}")
    return True


def handle_claude_stage(issue, state, dry_run):
    """Unassigned backlog child: act on Claude Supervisor's spec/code review
    once it has been posted."""
    if issue.get("assigneeAgentId") or issue.get("assigneeUserId"):
        return False
    comments = list_issue_comments(issue["id"])
    stage, stage_idx = current_stage(comments)
    if stage not in ("spec", "code"):
        return False
    review = pending_claude_review(comments, stage, stage_idx)
    if not review or state["review_acted"].get(issue["id"]) == review.get("id"):
        return False

    body = review.get("body") or ""
    key = label(issue)
    if stage == "spec":
        verdict = pick_verdict(body, ("needs-clarification", "ready"), "needs-clarification")
    else:
        verdict = pick_verdict(body, ("needs-human-look", "rework", "approve"), "needs-human-look")
    print(f"[{now()}] {key}: Claude {stage} review verdict={verdict}")
    if dry_run:
        return True

    if stage == "spec" and verdict == "ready":
        enhanced = parse_section(body, "enhanced request", ("questions",)) or body
        original = (issue.get("description") or "").split(ENHANCED_HEADER)[0].rstrip()
        update_issue(issue["id"], description=f"{original}\n\n---\n{ENHANCED_HEADER}\n{enhanced}\n")
        send_to_sam(issue, "Pipeline: Claude reviewed and enhanced the request (see description) — handing to dev (Sam).", state)
        notify(f"\U0001f4dd→\U0001f527 {key}: request enhanced, handing to Sam. ({issue.get('title', '')})")
    elif stage == "spec":
        questions = parse_section(body, "questions") or "(see Claude's review on the issue)"
        update_issue(
            issue["id"],
            status="blocked",
            assignee=None,
            comment=f"Pipeline: Claude needs clarification before dev can start. Answer on the issue, then set "
            f"status back to backlog to re-run the spec review. {tag('spec')}",
        )
        post_slack(
            f"❓ {key} needs clarification before work can start. ({issue.get('title', '')})\n{clip(questions, 600)}"
        )
    elif verdict == "approve":
        tests = parse_section(body, "test requests", ("risk flags",)) or "(none supplied — run the standard suite)"
        update_issue(
            issue["id"],
            status="todo",
            assignee=LYNN_ID,
            comment=f"Pipeline: Claude reviewed the change against the request and approved — handing to QA (Lynn).\n\n"
            f"**Test requests from Claude:**\n{tests}\n\n{tag('qa')}",
        )
        notify(f"\U0001f50e→\U0001f9ea {key}: code approved, handing to Lynn. ({issue.get('title', '')})")
    elif verdict == "rework":
        items = parse_section(body, "rework items", ("test requests", "risk flags")) or "(see Claude's review)"
        if send_to_sam(
            issue, f"Pipeline: Claude's code review found the change does not yet meet the request.\n\n**Rework items:**\n{items}", state, rework=True
        ):
            notify(f"\U0001f50e→\U0001f527 {key}: Claude sent it back to Sam. ({issue.get('title', '')})")
    else:
        update_issue(
            issue["id"],
            status="blocked",
            assignee=None,
            comment=f"Pipeline: Claude could not verify the change and wants a human look. Set status back to "
            f"backlog to re-run the review. {tag('code')}",
        )
        post_slack(
            f"⚠️ {key}: Claude could not verify the code change and needs your look. ({issue.get('title', '')})"
        )
    state["review_acted"][issue["id"]] = review.get("id")
    return True


def handle_done(issue, state, dry_run):
    key = label(issue)
    assignee = issue.get("assigneeAgentId")
    ddkey = dedup_key(issue)
    if state["advanced"].get(issue["id"]) == ddkey:
        return False
    if assignee not in (SAM_ID, LYNN_ID, AARON_ID):
        return False  # done, but not a pipeline role (e.g. already closed by Ram)

    print(f"[{now()}] {key}: done at {STAGE_NAME[assignee]}")
    if dry_run:
        return True

    if assignee == SAM_ID:
        update_issue(
            issue["id"],
            status="backlog",
            assignee=None,
            comment=f"Pipeline: dev complete — handing to Claude for code review against the request. {tag('code')}",
        )
        notify(f"\U0001f527→\U0001f50e {key}: dev complete, awaiting Claude review. ({issue.get('title', '')})")
    elif assignee == LYNN_ID:
        update_issue(
            issue["id"],
            status="todo",
            assignee=AARON_ID,
            comment=f"Pipeline: QA passed — handing to devops (Aaron) for deploy. {tag('deploy')}",
        )
        notify(f"\U0001f9ea→\U0001f680 {key}: QA passed, handing to Aaron. ({issue.get('title', '')})")
    else:
        publish_and_close(issue, state)
    state["advanced"][issue["id"]] = ddkey
    return True


def slack_origin(epic):
    m = SLACK_ORIGIN_RE.search((epic or {}).get("description") or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def publish_and_close(issue, state):
    """Final stage: Ram (the bot identity) reports the result in Slack, then
    the issue and its epic are closed."""
    key = label(issue)
    comments = list_issue_comments(issue["id"])
    try:
        epic = get_issue(issue["parentId"])
    except Exception as e:  # epic is only needed for Slack routing/closing
        print(f"  could not read epic {issue['parentId']}: {e}", file=sys.stderr)
        epic = None
    channel, thread_ts = slack_origin(epic)

    aaron = last_comment_by(comments, AARON_ID)
    lynn = last_comment_by(comments, LYNN_ID)
    review = next((c for c in reversed(comments) if CODE_MARK in (c.get("body") or "")), None)
    lines = [f"✅ *{key} is done — {issue.get('title', '')}*"]
    if aaron:
        lines.append(f"• *Deployed:* {clip(aaron.get('body'), 350)}")
    if lynn:
        lines.append(f"• *QA:* {clip(lynn.get('body'), 250)}")
    if review:
        why = parse_section(review.get("body") or "", "why", ("rework items", "test requests", "risk flags"))
        if why:
            lines.append(f"• *Review:* {clip(why, 250)}")
    lines.append("Pipeline: request → Claude spec review → Sam → Claude code review → Lynn → Aaron.")

    if not state["published"].get(issue["id"]):
        post_slack("\n".join(lines), channel=channel, thread_ts=thread_ts)
        state["published"][issue["id"]] = True
    update_issue(
        issue["id"],
        status="done",
        assignee=RAM_ID,
        comment="Ram: result published to Slack; closing.",
    )
    if epic and epic.get("status") != "done":
        update_issue(epic["id"], status="done")
    print(f"[{now()}] {key}: published to Slack ({'thread' if thread_ts else 'DM'}) and closed")


def looks_like_code_bug(text):
    return "code_bug" in (text or "").lower()


def handle_blocked(issue, state, dry_run, why="BLOCKED"):
    key = label(issue)
    assignee = issue.get("assigneeAgentId")
    if assignee not in (SAM_ID, LYNN_ID, AARON_ID):
        return False  # unassigned blocks were already announced by the handler that set them
    ddkey = dedup_key(issue)
    if state["blocked_notified"].get(issue["id"]) == ddkey:
        return False

    comments = list_issue_comments(issue["id"])
    last = last_comment_by(comments, assignee) or (comments[-1] if comments else None)
    last_body = (last or {}).get("body") or "(no comment)"
    print(f"[{now()}] {key}: {why.lower()} at {STAGE_NAME[assignee]}")
    if dry_run:
        return True

    if assignee == LYNN_ID and why == "BLOCKED" and looks_like_code_bug(last_body):
        sent = send_to_sam(
            issue,
            f"Pipeline: QA failed with a code bug — sending back to dev (Sam).\n\n**Lynn's findings:**\n{clip(last_body, 1500)}",
            state,
            rework=True,
        )
        if sent:
            notify(f"\U0001f9ea→\U0001f527 {key}: QA found a code bug, back to Sam. ({issue.get('title', '')})")
    else:
        post_slack(
            f"\U0001f6d1 {key} is {why} at {STAGE_NAME[assignee]} and needs a human look.\n"
            f"({issue.get('title', '')})\nLatest note: {clip(last_body, 300)}"
        )
    state["blocked_notified"][issue["id"]] = ddkey
    return True


def run_once(args, state):
    candidates = list_pipeline_candidates(args.company_id)
    acted = 0
    for issue in candidates:
        status = issue.get("status")
        try:
            if status == "backlog":
                acted += handle_claude_stage(issue, state, args.dry_run)
            elif status == "done":
                acted += handle_done(issue, state, args.dry_run)
            elif status == "blocked":
                acted += handle_blocked(issue, state, args.dry_run)
            elif status == "in_review":
                acted += handle_blocked(issue, state, args.dry_run, why="waiting on a human review")
        except Exception as e:
            print(f"error handling {label(issue)}: {e}", file=sys.stderr)
            traceback.print_exc()
        if not args.dry_run:
            save_state(state)  # per-issue: a later crash must not forget an earlier Slack post
    print(f"done: {len(candidates)} pipeline-enrolled candidate(s), {acted} action(s) taken")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company-id", dest="company_id", default=os.environ.get("PAPERCLIP_COMPANY_ID"))
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would happen but never write to Paperclip or Slack",
    )
    args = p.parse_args()

    if not args.company_id:
        p.error("missing required config: company_id (env PAPERCLIP_COMPANY_ID or --company-id)")

    state = load_state()
    if args.once:
        run_once(args, state)
        return
    # Not expected in production (the systemd timer drives --once) but kept
    # for local testing.
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
