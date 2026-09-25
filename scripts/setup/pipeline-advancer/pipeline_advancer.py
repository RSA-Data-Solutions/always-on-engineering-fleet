#!/usr/bin/env python3
"""Pipeline Advancer daemon.

Drives an *enrolled* Paperclip issue through the fleet's delivery pipeline and is the ONLY
component that routes issues between stages. Sam, Lynn and Aaron just do their stage and
report; Claude Supervisor writes the reviews; this daemon reads the result and does the
handoff, leaving a comment on the issue at every transition.

Enrollment: an issue is "in the pipeline" if it has a non-null `parentId`. For a Slack request
Ram files a parent "epic" (its description carries the Slack origin, see SLACK_ORIGIN) and one
child (the request). Both start unassigned in `backlog`. Flat issues are never touched.

The pipeline:

    Slack -> Ram (acknowledges, files epic + child via `ram-file`)
      1 SPEC    Claude Supervisor writes "**Claude spec review**".
                ready              -> a git worktree + branch is cut for the issue, the
                                      description is enriched, Sam gets it
                needs-clarification -> blocked, Slack question
      2 DEV     Sam works in the worktree, sets done.
                done               -> safety-net commit of anything uncommitted, then stage code
      3 REVIEW  Claude Supervisor writes "**Claude code review**" against the worktree diff.
                approve            -> Lynn, with Claude's test requests
                rework             -> Sam, with the rework items      (counts toward the cap)
                needs-human-look   -> blocked, Slack
      4 QA      Lynn tests in the worktree.
                done               -> the branch is MERGED INTO MAIN and pushed (production
                                      deploys are the operator's CI/CD, triggered by main), then Aaron
                blocked + code_bug -> Sam (rework)
                blocked otherwise  -> paused, Slack
      5 DEPLOY  Aaron deploys from main, sets done.
                done               -> result posted to Slack in Ram's name, issue + epic closed,
                                      worktree removed

Robustness added 2026-09-24 after the first real runs:

* A queue per agent. The local model serves one request at a time; three concurrent Sam runs
  starved each other into 30-minute timeouts. An agent gets one pipeline issue at a time; others
  wait (unassigned, `[pipeline-stage: queue-<role>]`) and start automatically, oldest first.
* Silent runs. Local models often end a run without setting a status, and Paperclip then
  escalates to "board decision required". When an agent's run ended that way (or an
  `in_progress` issue has had no live run for PIPELINE_STALL_MINUTES), the issue goes to Claude
  Supervisor for a "**Claude disposition check**" (complete / failed / unclear) and this daemon
  acts on the verdict. Sam's "complete" still faces the code review; Lynn's must show passing
  tests; nothing is trusted on narration alone.
* Per-issue git worktrees (pipeline_git.py) so parallel work can't collide and the reviewer
  always has a real diff.

Why Claude's stages are "unassigned + backlog" rather than assigned to the Claude Supervisor
agent: verified 2026-09-23 — assigning an issue to a process-adapter agent wakes it, and when
the run ends without a disposition Paperclip auto-blocks the issue. The stage is carried by a
`[pipeline-stage: X]` tag in this daemon's comments; claude_supervisor.py reads the same tag.

Writes use the board workaround key over the HTTP API (the CLI cannot clear an assignee, and the
run-scoped key 403s on issue writes due to upstream bug paperclipai/paperclip#13708).
"""
import argparse
import datetime
import fcntl
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pipeline_gate as gate  # noqa: E402
import pipeline_git as pg  # noqa: E402

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

# Real, confirmed agent ids for this company — override via env if the org chart changes.
SAM_ID = os.environ.get("PIPELINE_SAM_AGENT_ID", "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0")
LYNN_ID = os.environ.get("PIPELINE_LYNN_AGENT_ID", "d053dfe0-dbd6-45fd-8069-32b51a00580e")
AARON_ID = os.environ.get("PIPELINE_AARON_AGENT_ID", "a02a6b9e-4d44-4f46-b373-83c15e6309c0")
RAM_ID = os.environ.get("PIPELINE_RAM_AGENT_ID", "093a44a5-da1d-421a-9708-cd1f05e6d734")

ROLE_AGENT = {"dev": SAM_ID, "qa": LYNN_ID, "deploy": AARON_ID}
AGENT_ROLE = {v: k for k, v in ROLE_AGENT.items()}
STAGE_NAME = {SAM_ID: "dev (Sam)", LYNN_ID: "QA (Lynn)", AARON_ID: "devops (Aaron)"}
AGENT_NAME = {SAM_ID: "Sam", LYNN_ID: "Lynn", AARON_ID: "Aaron", RAM_ID: "Ram"}
WORKERS = (SAM_ID, LYNN_ID, AARON_ID)


def cfg(name, default=""):
    """Setting from the process env, else from ~/.pipeline-advancer/.env — Paperclip's process
    adapter does not source that file, so optional tunables must be read from disk too."""
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


def _truthy(value):
    return str(value).lower() in ("1", "true", "yes", "on")


MAX_REWORK = int(cfg("PIPELINE_MAX_REWORK", "2"))
STALL_MINUTES = int(cfg("PIPELINE_STALL_MINUTES", "20"))
MAX_CHECKS = int(cfg("PIPELINE_MAX_CHECKS", "3"))
# After Lynn approves, merge into main and push (the operator's CI/CD deploys from main).
MERGE_PUSH = _truthy(cfg("PIPELINE_MERGE_PUSH", "1"))
# Cloud route for the dev stage (per-issue model override; Paperclip merges
# assigneeAdapterOverrides.adapterConfig over the agent's own config, so only model/provider change).
#   off       always the local model (default: nothing spends Claude usage)
#   escalate  local first; run on Claude once the local model has failed at this issue
#             (a silent/stalled run, or PIPELINE_CLOUD_AFTER_REWORK reworks)
#   always    every dev run on Claude
CLOUD_MODE = cfg("PIPELINE_CLOUD_DEV", "off").lower()
CLOUD_MODEL = cfg("PIPELINE_CLOUD_MODEL", "claude-sonnet-5")
CLOUD_PROVIDER = cfg("PIPELINE_CLOUD_PROVIDER", "anthropic")
CLOUD_AFTER_REWORK = int(cfg("PIPELINE_CLOUD_AFTER_REWORK", "2"))
# Only "blocked / needs a human" and the final result reach Slack unless this is set.
SLACK_VERBOSE = _truthy(cfg("PIPELINE_SLACK_VERBOSE"))

# Markers shared with claude_supervisor.py (separate copies on purpose: no runtime dependency).
SPEC_MARK = "**Claude spec review**"
CODE_MARK = "**Claude code review**"
CHECK_MARK = "**Claude disposition check**"
STAGE_TAG_RE = re.compile(r"\[pipeline-stage:\s*([a-z-]+)\]", re.IGNORECASE)
WT_TAG_RE = re.compile(r"\[pipeline-worktree:\s*repo=(\S+)\s+path=(\S+)\s+branch=(\S+)\]")
ROLE_TAG_RE = re.compile(r"\[pipeline-role:\s*([a-z]+)\]")
ENHANCED_HEADER = "## Enhanced request (Claude spec review)"
MISSING_DISPOSITION_RE = re.compile(r"needs a disposition|missing disposition", re.IGNORECASE)
# Ram records where the request came from on the epic, e.g.
#   SLACK_ORIGIN: thread_ts=1790059229.120989
#   SLACK_ORIGIN: channel=C0123ABC thread_ts=1790059229.120989
# `channel` is optional: with none, the result goes to the configured user's DM and into
# `thread_ts` if given.
SLACK_ORIGIN_RE = re.compile(
    r"SLACK_ORIGIN:\s*(?:channel=([A-Z0-9]+))?\s*(?:thread_ts=([0-9]+\.[0-9]+))?", re.IGNORECASE
)

_UNSET = object()  # "leave this field alone" vs None == "clear it"


def now():
    return datetime.datetime.now().isoformat()


def load_env_file():
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
    """paperclipai/paperclip#13708 workaround; revert to the run-scoped key once it ships."""
    key = load_env_file().get("PAPERCLIP_BOARD_KEY_WORKAROUND")
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


STATE_KEYS = ("advanced", "blocked_notified", "review_acted", "rework", "published", "merged", "checks", "retry")


def load_state():
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    for key in STATE_KEYS:
        state.setdefault(key, {})
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def paperclip(*args):
    """Run the paperclipai CLI (read-only use) with the run-scoped key Paperclip injects."""
    cmd = ["paperclipai", *args, "--api-key", os.environ["PAPERCLIP_API_KEY"]]
    run_id = os.environ.get("PAPERCLIP_RUN_ID")
    if run_id:
        cmd += ["--run-id", run_id]
    cmd += ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"paperclipai {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


CANDIDATE_STATUSES = ("backlog", "todo", "in_progress", "done", "blocked", "in_review")


def list_pipeline_candidates(company_id):
    """One list call per status (the CLI filter takes a single value). todo/in_progress are
    read for the per-agent queue and the stall watchdog; only enrolled children are kept."""
    issues = []
    for status in CANDIDATE_STATUSES:
        issues.extend(paperclip("issue", "list", "--company-id", company_id, "--status", status))
    return [i for i in issues if i.get("parentId")]


def get_issue(issue_id):
    return paperclip("issue", "get", issue_id)


def list_issue_comments(issue_id):
    comments = paperclip("issue", "comments", issue_id)
    return sorted(comments, key=lambda c: c.get("createdAt") or "")


# Paperclip rejects `status=blocked` (422 "Entering blocked requires unresolved blockers, a
# pending interaction/approval, or unblockDescriptor") unless told who unblocks it. Every block
# this daemon sets is waiting on a human.
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


def update_issue(issue_id, status=_UNSET, assignee=_UNSET, comment=_UNSET, description=_UNSET, overrides=_UNSET):
    """`assignee=None` clears the assignee (the CLI can't express that, hence the HTTP API)."""
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
    if overrides is not _UNSET:
        body["assigneeAdapterOverrides"] = overrides  # None clears a previous override
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
    """Post as the Slack bot (Ram's identity). No channel -> the configured user's DM; a thread_ts
    needs the real DM channel id, so resolve it first and fall back to un-threaded."""
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
    """Text after a `NAME:` heading line up to the next heading in `next_names`."""
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
    """(stage, index of the comment that set it). Default 'spec': a fresh child has no pipeline
    comment yet and needs the spec review."""
    stage, idx = "spec", -1
    for i, c in enumerate(comments):
        m = STAGE_TAG_RE.search(c.get("body") or "")
        if m:
            stage, idx = m.group(1).lower(), i
    return stage, idx


def claude_review_after(comments, mark, stage_idx):
    """Latest Claude comment carrying `mark`, posted after the stage was entered, or None."""
    found = None
    for i, c in enumerate(comments):
        if i > stage_idx and mark in (c.get("body") or ""):
            found = c
    return found


def worktree_info(comments):
    """Latest [pipeline-worktree: ...] tag -> {repo, path, branch}, or None (legacy issues)."""
    info = None
    for c in comments:
        m = WT_TAG_RE.search(c.get("body") or "")
        if m:
            info = {"repo": m.group(1), "path": m.group(2), "branch": m.group(3)}
    return info


def wt_tag(repo, wt):
    return f"[pipeline-worktree: repo={repo} path={wt['path']} branch={wt['branch']}]"


def last_comment_by(comments, agent_id):
    mine = [c for c in comments if c.get("authorAgentId") == agent_id]
    return mine[-1] if mine else None


def missing_disposition(comments):
    """True if Paperclip flagged the agent's run as ending without a disposition after the
    agent's last comment (its "needs a disposition" system message)."""
    last_agent = -1
    for i, c in enumerate(comments):
        if c.get("authorAgentId"):
            last_agent = i
    return any(
        c.get("authorType") == "system" and MISSING_DISPOSITION_RE.search(c.get("body") or "")
        for c in comments[last_agent + 1 :]
    )


def age_minutes(iso):
    try:
        t = datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return 0
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60


def tag(stage):
    return f"[pipeline-stage: {stage}]"


def dedup_key(issue):
    return f"{issue['id']}:{issue.get('status')}:{issue.get('statusVersion')}"


def label(issue):
    return issue.get("identifier") or issue["id"]


def clip(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def looks_like_code_bug(text):
    return "code_bug" in (text or "").lower()


# ------------------------------------------------------------ queue / dispatch


def build_ctx(candidates):
    """busy: agent id -> identifiers of pipeline issues it currently holds (todo/in_progress)."""
    busy = {}
    for i in candidates:
        if i.get("status") in ("todo", "in_progress") and i.get("assigneeAgentId") in WORKERS:
            busy.setdefault(i["assigneeAgentId"], set()).add(label(i))
    return {"busy": busy, "candidates": candidates}


def cloud_dev(issue_id, state):
    """Should this issue's next dev run go to Claude instead of the local model?"""
    if CLOUD_MODE == "always":
        return True
    if CLOUD_MODE == "escalate" and state:
        failed_silently = state["checks"].get(issue_id, 0) or state["retry"].get(issue_id, 0)
        return bool(failed_silently or state["rework"].get(issue_id, 0) >= CLOUD_AFTER_REWORK)
    return False


def dev_overrides(issue_id, state):
    """(override to send, note for the comment). None clears any previous override, so a later
    run of the same issue is local again unless it escalates."""
    if cloud_dev(issue_id, state):
        return ({"adapterConfig": {"model": CLOUD_MODEL, "provider": CLOUD_PROVIDER}},
                f"\n\nPipeline: this attempt runs on Claude (`{CLOUD_MODEL}`) because the local model has not managed to finish it.")
    return None, ""


def dispatch(issue, role, text, ctx, extra="", state=None):
    """Give the issue to the agent for `role` if it is free, otherwise park it in that agent's
    queue. Returns 'started' or 'queued'. `text` is the handoff comment either way, so the agent
    finds everything it needs when its turn comes."""
    agent = ROLE_AGENT[role]
    key = label(issue)
    others = ctx["busy"].get(agent, set()) - {key}
    if others:
        update_issue(
            issue["id"],
            status="backlog",
            assignee=None,
            comment=f"{text}\n\nPipeline: {AGENT_NAME[agent]} is busy with {', '.join(sorted(others))} — queued; "
            f"it will start automatically when {AGENT_NAME[agent]} is free. {extra} {tag('queue-' + role)}".replace("  ", " "),
        )
        return "queued"
    # The override lives on the ISSUE and applies to whichever agent is assigned, so every dispatch
    # sets it explicitly: Claude for an escalated dev run, None (cleared) for everything else —
    # otherwise QA and deploy would silently inherit Sam's cloud override.
    overrides, note = dev_overrides(issue["id"], state) if role == "dev" else (None, "")
    extra_kwargs = {"overrides": overrides}
    update_issue(issue["id"], status="todo", assignee=agent,
                 comment=f"{text}{note}\n\n{extra} {tag(role)}".replace("  ", " "), **extra_kwargs)
    ctx["busy"].setdefault(agent, set()).add(key)
    return "started"


def handle_queue(issue, stage, ctx, state, dry_run):
    """Start a parked issue when its agent is free. run_once walks issues oldest-first and
    marks the agent busy as soon as one starts, so the queue is naturally first-in-first-out."""
    role = stage[len("queue-"):]
    if role not in ROLE_AGENT:
        return False
    agent = ROLE_AGENT[role]
    if ctx["busy"].get(agent):
        return False
    print(f"[{now()}] {label(issue)}: {AGENT_NAME[agent]} is free — starting queued {role}")
    if dry_run:
        return True
    overrides, note = dev_overrides(issue["id"], state) if role == "dev" else (None, "")
    extra_kwargs = {"overrides": overrides}
    update_issue(
        issue["id"], status="todo", assignee=agent,
        comment=f"Pipeline: {AGENT_NAME[agent]} is free — starting.{note} {tag(role)}", **extra_kwargs,
    )
    ctx["busy"].setdefault(agent, set()).add(label(issue))
    return True


def block_for_human(issue, why, stage, slack_text):
    """Pause on a human: block the issue, tag the stage to resume at, and tell them on Slack."""
    update_issue(
        issue["id"], status="blocked", assignee=None,
        comment=f"Pipeline: {why} Set status back to backlog to re-run once resolved. {tag(stage)}",
    )
    post_slack(slack_text)


def wt_instructions(comments):
    wt = worktree_info(comments)
    if not wt:
        return ""
    return (
        f"\n\n**Work ONLY in this git worktree** (branch `{wt['branch']}`, cut from main): `{wt['path']}`\n"
        f"`cd` there first. Commit your work there with a message starting `{wt['branch'].upper()}:`. "
        "Do not touch any other checkout, do not push, and do not create report/summary files."
    )


def send_to_sam(issue, comment, state, ctx, rework=False):
    """Put the issue in Sam's queue. Returns False (and blocks it) when a rework would exceed the cap."""
    if rework:
        n = state["rework"].get(issue["id"], 0) + 1
        if n > MAX_REWORK:
            block_for_human(
                issue, f"rework limit ({MAX_REWORK}) reached.", "dev",
                f"\U0001f6d1 {label(issue)} bounced back to dev more than {MAX_REWORK} times and is paused "
                f"for a human look. ({issue.get('title', '')})",
            )
            return False
        state["rework"][issue["id"]] = n
        comment = f"Pipeline: rework {n}/{MAX_REWORK}.\n\n{comment}"
    comments = list_issue_comments(issue["id"])
    dispatch(issue, "dev", comment + wt_instructions(comments), ctx, state=state)
    return True


# --------------------------------------------------------------- stage: Claude reviews


def handle_claude_stage(issue, stage, stage_idx, comments, state, ctx, dry_run):
    """Unassigned backlog child: act on Claude Supervisor's spec/code review once posted."""
    mark = SPEC_MARK if stage == "spec" else CODE_MARK
    review = claude_review_after(comments, mark, stage_idx)
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
        project = (parse_field(body, "project") or "").split()[0:1]
        repo = pg.repo_for_project(project[0] if project else "")
        if not repo:
            block_for_human(
                issue, f"Claude's spec review says the owning project is '{project[0] if project else '?'}', "
                "which has no local repo mapped.", "spec",
                f"❓ {key}: I can't tell which project repo owns this change (Claude said "
                f"'{project[0] if project else '?'}'). Tell Ram which one (IBMiMCP / iNova / fleet). ({issue.get('title', '')})",
            )
        else:
            try:
                wt = pg.create_worktree(repo, key)
            except Exception as e:
                block_for_human(
                    issue, f"could not create a git worktree in {repo}: {e}", "spec",
                    f"\U0001f6d1 {key}: could not create a git worktree in {repo} — {clip(str(e), 300)}",
                )
                state["review_acted"][issue["id"]] = review.get("id")
                return True
            enhanced = parse_section(body, "enhanced request", ("questions",)) or body
            original = (issue.get("description") or "").split(ENHANCED_HEADER)[0].rstrip()
            update_issue(issue["id"], description=f"{original}\n\n---\n{ENHANCED_HEADER}\n{enhanced}\n")
            text = "Pipeline: Claude reviewed and enhanced the request (see description) — handing to dev (Sam)."
            wtc = [{"body": wt_tag(repo, wt)}]
            dispatch(issue, "dev", text + wt_instructions(wtc), ctx, extra=wt_tag(repo, wt), state=state)
            notify(f"\U0001f4dd→\U0001f527 {key}: request enhanced, handing to Sam. ({issue.get('title', '')})")
    elif stage == "spec":
        questions = parse_section(body, "questions") or "(see Claude's review on the issue)"
        block_for_human(
            issue, "Claude needs clarification before dev can start. Answer via Ram in Slack.", "spec",
            f"❓ {key} needs clarification before work can start. ({issue.get('title', '')})\n{clip(questions, 600)}",
        )
    elif verdict == "approve":
        tests = parse_section(body, "test requests", ("risk flags",)) or "(none supplied — run the standard suite)"
        wt = worktree_info(comments)
        where = f"\n\n**Test in this worktree (branch `{wt['branch']}`):** `{wt['path']}`" if wt else ""
        dispatch(
            issue, "qa",
            f"Pipeline: Claude reviewed the change against the request and approved — handing to QA (Lynn).\n\n"
            f"**Test requests from Claude:**\n{tests}{where}",
            ctx,
        )
        notify(f"\U0001f50e→\U0001f9ea {key}: code approved, handing to Lynn. ({issue.get('title', '')})")
    elif verdict == "rework":
        items = parse_section(body, "rework items", ("test requests", "risk flags")) or "(see Claude's review)"
        if send_to_sam(
            issue, f"Pipeline: Claude's code review found the change does not yet meet the request.\n\n**Rework items:**\n{items}",
            state, ctx, rework=True,
        ):
            notify(f"\U0001f50e→\U0001f527 {key}: Claude sent it back to Sam. ({issue.get('title', '')})")
    else:
        block_for_human(
            issue, "Claude could not verify the change.", "code",
            f"⚠️ {key}: Claude could not verify the code change and needs your look. ({issue.get('title', '')})",
        )
    state["review_acted"][issue["id"]] = review.get("id")
    return True


# -------------------------------------------------------------- stage completion


def finish_dev(issue, comments, state, ctx):
    """Sam is done: commit any loose work, run the deterministic build gate, and only if it
    passes hand to Claude's code review. A failing gate goes straight back to Sam."""
    key = label(issue)
    wt = worktree_info(comments)
    note = gate_line = ""
    if wt:
        try:
            sha = pg.commit_worktree(wt["path"], key, issue.get("title", ""))
            note = f" (safety-net commit {sha[:8]} of uncommitted work)" if sha else ""
        except Exception as e:
            note = f" (safety-net commit failed: {clip(str(e), 120)})"
        project = pathlib.Path(wt["repo"]).name.lower()
        try:
            g = gate.run_gate(project, wt["path"])
        except Exception as e:
            block_for_human(issue, f"the build gate could not run: {e}", "code",
                            f"🛑 {key}: the build gate could not run — {clip(str(e), 300)}")
            return
        if not g["ok"]:
            print(f"[{now()}] {key}: {g['summary']}")
            send_to_sam(
                issue,
                f"Pipeline: the automatic build gate FAILED at '{g['failed']}'. Fix this in your worktree, commit, "
                f"and set the issue to done again.\n\n```\n{g['detail']}\n```",
                state, ctx, rework=True,
            )
            return
        if g["lockfile_changed"]:
            try:
                pg.commit_worktree(wt["path"], key, f"{issue.get('title', '')} (update package-lock.json)")
            except Exception as e:
                note += f" (lockfile commit failed: {clip(str(e), 120)})"
        gate_line = f" {g['summary']}."
    update_issue(
        issue["id"], status="backlog", assignee=None,
        comment=f"Pipeline: dev complete{note}.{gate_line} Handing to Claude for code review against the request. {tag('code')}",
    )
    notify(f"\U0001f527→\U0001f50e {key}: dev complete, awaiting Claude review. ({issue.get('title', '')})")


def finish_qa(issue, comments, state, ctx):
    """Lynn approved: merge the branch into main (and push), then hand to Aaron."""
    key = label(issue)
    wt = worktree_info(comments)
    if wt and not state["merged"].get(issue["id"]):
        try:
            r = pg.merge_to_main(wt["repo"], wt["branch"], key, issue.get("title", ""), push=MERGE_PUSH)
        except Exception as e:
            block_for_human(issue, f"QA passed but the merge into main failed: {e}", "qa",
                            f"\U0001f6d1 {key}: QA passed but merging into main failed — {clip(str(e), 300)}")
            return
        if r["status"] == "conflict":
            block_for_human(issue, "QA passed but the branch conflicts with main.", "qa",
                            f"\U0001f6d1 {key}: QA passed but `{wt['branch']}` conflicts with main — needs a human "
                            f"or a rebase.\n{clip(r['detail'], 300)}")
            return
        if r["status"] == "push_failed":
            block_for_human(issue, f"QA passed and the branch merges cleanly, but pushing to main was rejected: "
                            f"{r['detail']}. The branch `{wt['branch']}` was pushed for a PR.", "qa",
                            f"\U0001f6d1 {key}: QA passed, but pushing to main was rejected ({clip(r['detail'], 200)}). "
                            f"Branch `{wt['branch']}` is pushed — open a PR.")
            return
        state["merged"][issue["id"]] = r["sha"]
        where = "merged into `main` and pushed" if r.get("pushed") else "merged into local `main` (push disabled)"
        text = (f"Pipeline: QA passed — `{wt['branch']}` {where} ({r['sha'][:8]}). "
                f"Production deploy is your CI/CD's. {r.get('note', '')}\n\n"
                "Handing to devops (Aaron): deploy/verify from the main checkout. Do NOT commit, merge or push anything.")
    elif wt:
        text = "Pipeline: QA passed (already merged into main) — handing to devops (Aaron). Do NOT commit, merge or push anything."
    else:
        text = "Pipeline: QA passed — handing to devops (Aaron) for deploy."
    dispatch(issue, "deploy", text, ctx)
    notify(f"\U0001f9ea→\U0001f680 {key}: QA passed, merged, handing to Aaron. ({issue.get('title', '')})")


def slack_origin(epic):
    m = SLACK_ORIGIN_RE.search((epic or {}).get("description") or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def finish_deploy(issue, comments, state, ctx):
    """Final stage: Ram (the bot identity) reports the result in Slack, then the issue and epic
    are closed and the worktree removed."""
    key = label(issue)
    try:
        epic = get_issue(issue["parentId"])
    except Exception as e:
        print(f"  could not read epic {issue['parentId']}: {e}", file=sys.stderr)
        epic = None
    channel, thread_ts = slack_origin(epic)

    aaron = last_comment_by(comments, AARON_ID)
    lynn = last_comment_by(comments, LYNN_ID)
    review = next((c for c in reversed(comments) if CODE_MARK in (c.get("body") or "")), None)
    lines = [f"✅ *{key} is done — {issue.get('title', '')}*"]
    wt = worktree_info(comments)
    if state["merged"].get(issue["id"]) and wt:
        lines.append(f"• *Merged:* `{wt['branch']}` → `main` ({state['merged'][issue['id']][:8]}) — production deploy is your CI/CD.")
    if aaron:
        lines.append(f"• *Deployed:* {clip(aaron.get('body'), 350)}")
    if lynn:
        lines.append(f"• *QA:* {clip(lynn.get('body'), 250)}")
    if review:
        why = parse_section(review.get("body") or "", "why", ("rework items", "test requests", "risk flags"))
        if why:
            lines.append(f"• *Review:* {clip(why, 250)}")
    lines.append("Pipeline: request → Claude spec review → Sam → Claude code review → Lynn → merge → Aaron.")

    if not state["published"].get(issue["id"]):
        post_slack("\n".join(lines), channel=channel, thread_ts=thread_ts)
        state["published"][issue["id"]] = True
    update_issue(issue["id"], status="done", assignee=RAM_ID, comment="Ram: result published to Slack; closing.")
    if epic and epic.get("status") != "done":
        update_issue(epic["id"], status="done")
    if wt and state["merged"].get(issue["id"]):
        try:
            pg.cleanup_worktree(wt["repo"], wt["path"], wt["branch"])
        except Exception as e:
            print(f"  worktree cleanup failed: {e}", file=sys.stderr)
    print(f"[{now()}] {key}: published to Slack ({'thread' if thread_ts else 'DM'}) and closed")


FINISH = {"dev": finish_dev, "qa": finish_qa, "deploy": finish_deploy}


def handle_done(issue, state, ctx, dry_run):
    key = label(issue)
    assignee = issue.get("assigneeAgentId")
    ddkey = dedup_key(issue)
    if state["advanced"].get(issue["id"]) == ddkey or assignee not in WORKERS:
        return False
    role = AGENT_ROLE[assignee]
    print(f"[{now()}] {key}: done at {STAGE_NAME[assignee]}")
    if dry_run:
        return True
    ctx["busy"].get(assignee, set()).discard(key)
    FINISH[role](issue, list_issue_comments(issue["id"]), state, ctx)
    state["advanced"][issue["id"]] = ddkey
    return True


# ------------------------------------------- silent runs, stalls, blocked issues


def request_check(issue, role, why, state):
    """Hand a silent agent's issue to Claude for a disposition check (bounded)."""
    n = state["checks"].get(issue["id"], 0) + 1
    state["checks"][issue["id"]] = n
    agent = ROLE_AGENT[role]
    if n > MAX_CHECKS:
        block_for_human(
            issue, f"{AGENT_NAME[agent]} keeps ending runs without a status ({MAX_CHECKS} checks).", role,
            f"\U0001f6d1 {label(issue)}: {AGENT_NAME[agent]} keeps finishing without setting a status — needs a human look. "
            f"({issue.get('title', '')})",
        )
        return
    update_issue(
        issue["id"], status="backlog", assignee=None,
        comment=f"Pipeline: {AGENT_NAME[agent]}'s run ended without a status ({why}). Asking Claude to judge the "
        f"outcome from the last report. [pipeline-role: {role}] {tag('check-' + role)}",
    )


def handle_check(issue, stage, stage_idx, comments, state, ctx, dry_run):
    role = stage[len("check-"):]
    if role not in ROLE_AGENT:
        return False
    review = claude_review_after(comments, CHECK_MARK, stage_idx)
    if not review or state["review_acted"].get(issue["id"]) == review.get("id"):
        return False
    body = review.get("body") or ""
    verdict = pick_verdict(body, ("complete", "failed", "unclear"), "unclear")
    ftype = parse_field(body, "failure type") or ""
    agent, key = ROLE_AGENT[role], label(issue)
    print(f"[{now()}] {key}: Claude disposition check for {AGENT_NAME[agent]} verdict={verdict}")
    if dry_run:
        return True
    state["review_acted"][issue["id"]] = review.get("id")
    if verdict == "complete":
        FINISH[role](issue, comments, state, ctx)
    elif verdict == "failed" and role == "qa" and looks_like_code_bug(ftype):
        last = last_comment_by(comments, LYNN_ID)
        send_to_sam(issue, "Pipeline: QA failed with a code bug — sending back to dev (Sam).\n\n**Lynn's findings:**\n"
                    + clip((last or {}).get("body"), 1500), state, ctx, rework=True)
    elif verdict == "unclear" and state["retry"].get(issue["id"], 0) < 1:
        state["retry"][issue["id"]] = state["retry"].get(issue["id"], 0) + 1
        dispatch(issue, role,
                 f"Pipeline: your previous run ended without setting a status and Claude could not tell whether the "
                 f"work is finished. Finish anything outstanding, then set this issue to `done` (with what you did and "
                 f"the evidence) or `blocked` (with why). Do not just describe the work.", ctx, state=state)
    else:
        block_for_human(
            issue, f"{AGENT_NAME[agent]}'s run ended without a status and Claude judged it '{verdict}'.", role,
            f"⚠️ {key}: {AGENT_NAME[agent]} ended without a status; Claude judged it '{verdict}'. Needs your look. "
            f"({issue.get('title', '')})",
        )
    return True


def handle_stalled(issue, state, ctx, dry_run):
    """in_progress with no live run for a while -> the run died/timed out: judge it. todo that
    nobody picked up -> tell the human once."""
    assignee = issue.get("assigneeAgentId")
    if assignee not in WORKERS:
        return False
    age = age_minutes(issue.get("updatedAt"))
    if issue.get("status") == "in_progress" and not issue.get("executionRunId") and not issue.get("checkoutRunId") \
            and age >= STALL_MINUTES:
        print(f"[{now()}] {label(issue)}: no live run for {age:.0f} min at {STAGE_NAME[assignee]}")
        if dry_run:
            return True
        ctx["busy"].get(assignee, set()).discard(label(issue))
        request_check(issue, AGENT_ROLE[assignee], f"no live run for {age:.0f} min", state)
        return True
    if issue.get("status") == "todo" and age >= 3 * STALL_MINUTES and not issue.get("executionRunId"):
        ddkey = f"{dedup_key(issue)}:stalled-todo"
        if state["blocked_notified"].get(issue["id"]) == ddkey:
            return False
        if dry_run:
            return True
        post_slack(f"⏳ {label(issue)} has been waiting {age:.0f} min for {AGENT_NAME[assignee]} to start. "
                   f"({issue.get('title', '')})")
        state["blocked_notified"][issue["id"]] = ddkey
        return True
    return False


def handle_blocked(issue, state, ctx, dry_run, why="BLOCKED"):
    key = label(issue)
    assignee = issue.get("assigneeAgentId")
    if assignee not in WORKERS:
        return False  # unassigned blocks were announced by the handler that set them
    ddkey = dedup_key(issue)
    if state["blocked_notified"].get(issue["id"]) == ddkey:
        return False

    comments = list_issue_comments(issue["id"])
    if why == "BLOCKED" and missing_disposition(comments):
        print(f"[{now()}] {key}: {AGENT_NAME[assignee]} ended without a status (Paperclip escalated)")
        if dry_run:
            return True
        ctx["busy"].get(assignee, set()).discard(key)
        request_check(issue, AGENT_ROLE[assignee], "Paperclip flagged a missing disposition", state)
        state["blocked_notified"][issue["id"]] = ddkey
        return True

    last = last_comment_by(comments, assignee) or (comments[-1] if comments else None)
    last_body = (last or {}).get("body") or "(no comment)"
    print(f"[{now()}] {key}: {why.lower()} at {STAGE_NAME[assignee]}")
    if dry_run:
        return True
    if assignee == LYNN_ID and why == "BLOCKED" and looks_like_code_bug(last_body):
        if send_to_sam(
            issue,
            f"Pipeline: QA failed with a code bug — sending back to dev (Sam).\n\n**Lynn's findings:**\n{clip(last_body, 1500)}",
            state, ctx, rework=True,
        ):
            notify(f"\U0001f9ea→\U0001f527 {key}: QA found a code bug, back to Sam. ({issue.get('title', '')})")
    else:
        post_slack(
            f"\U0001f6d1 {key} is {why} at {STAGE_NAME[assignee]} and needs a human look.\n"
            f"({issue.get('title', '')})\nLatest note: {clip(last_body, 300)}"
        )
    state["blocked_notified"][issue["id"]] = ddkey
    return True


# ------------------------------------------------------------------ main loop


def handle_backlog(issue, ctx, state, dry_run):
    """Unassigned backlog child: Claude's stages, the per-agent queue, or a disposition check."""
    if issue.get("assigneeAgentId") or issue.get("assigneeUserId"):
        return False
    comments = list_issue_comments(issue["id"])
    stage, stage_idx = current_stage(comments)
    if stage in ("spec", "code"):
        return handle_claude_stage(issue, stage, stage_idx, comments, state, ctx, dry_run)
    if stage.startswith("queue-"):
        return handle_queue(issue, stage, ctx, state, dry_run)
    if stage.startswith("check-"):
        return handle_check(issue, stage, stage_idx, comments, state, ctx, dry_run)
    return False


def run_once(args, state):
    candidates = list_pipeline_candidates(args.company_id)
    ctx = build_ctx(candidates)
    acted = 0
    for issue in sorted(candidates, key=lambda i: i.get("createdAt") or ""):
        try:
            # The list is a snapshot and a pass can take minutes (a build gate, a merge). Re-read the
            # issue right before acting: a human may have cancelled or moved it meanwhile, and a stale
            # snapshot must never overwrite that (2026-09-24: a cancelled test issue was revived as
            # `blocked` three seconds after being cancelled, and later got worked on).
            fresh = get_issue(issue["id"])
            if (fresh.get("status"), fresh.get("assigneeAgentId")) != (issue.get("status"), issue.get("assigneeAgentId")):
                print(f"[{now()}] {label(issue)}: changed since the snapshot "
                      f"({issue.get('status')} -> {fresh.get('status')}); leaving it for the next pass")
                continue
            issue = fresh
            status = issue.get("status")
            if status == "backlog":
                acted += handle_backlog(issue, ctx, state, args.dry_run)
            elif status in ("todo", "in_progress"):
                acted += handle_stalled(issue, state, ctx, args.dry_run)
            elif status == "done":
                acted += handle_done(issue, state, ctx, args.dry_run)
            elif status == "blocked":
                acted += handle_blocked(issue, state, ctx, args.dry_run)
            elif status == "in_review":
                acted += handle_blocked(issue, state, ctx, args.dry_run, why="waiting on a human review")
        except Exception as e:
            print(f"error handling {label(issue)}: {e}", file=sys.stderr)
            traceback.print_exc()
        if not args.dry_run:
            save_state(state)  # per-issue: a later crash must not forget an earlier Slack post/merge
    print(f"done: {len(candidates)} pipeline-enrolled candidate(s), {acted} action(s) taken")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company-id", dest="company_id", default=os.environ.get("PAPERCLIP_COMPANY_ID"))
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument("--dry-run", action="store_true", help="list what would happen but never write to Paperclip, git or Slack")
    args = p.parse_args()

    if not args.company_id:
        p.error("missing required config: company_id (env PAPERCLIP_COMPANY_ID or --company-id)")

    # One run at a time: a build gate can take minutes and the timer fires every 30s; two runs
    # would both act on the same issue (double merge, double Slack post).
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_FILE.parent / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another pipeline_advancer run holds the lock — exiting")
        return

    state = load_state()
    if args.once:
        run_once(args, state)
        return
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
