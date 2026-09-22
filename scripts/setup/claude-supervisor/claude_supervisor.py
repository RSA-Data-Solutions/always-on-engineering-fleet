#!/usr/bin/env python3
"""Claude Supervisor daemon.

Polls Paperclip for issues in `in_review` status across the fleet's one
project, asks Claude for an independent second opinion, and records the
result as a Paperclip approval request. It never changes an issue's status,
never touches GitHub, never writes to any repo, and holds no credential
except its own scoped Paperclip API key and the Anthropic API key.

See README.md in this directory for the build plan, what is verified vs.
assumed about the `paperclipai` CLI surface, and the manual setup steps this
script depends on (a Paperclip agent identity + API key for claude-supervisor
must already exist before this will do anything useful).
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time

STATE_FILE = pathlib.Path(
    os.environ.get(
        "CLAUDE_SUPERVISOR_STATE",
        str(pathlib.Path.home() / ".claude-supervisor" / "reviewed.json"),
    )
)

# Local repo paths, used only for a best-effort commit lookup so a review can
# see real diff content instead of relying solely on an agent's self-report.
# Purely additive context — reviews still run without a match.
REPO_MAP = {
    "ibmimcp": os.environ.get(
        "IBMIMCP_REPO_PATH", "/home/sashi/Documents/projects/RSA/IBMiMCP"
    ),
    "inova": os.environ.get(
        "INOVA_REPO_PATH", "/home/sashi/Documents/projects/RSA/inova"
    ),
    "fleet": os.environ.get(
        "FLEET_REPO_PATH",
        "/home/sashi/Documents/projects/RSA/always-on-engineering-fleet",
    ),
}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"reviewed_issue_updated_at": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def paperclip(*args):
    """Run the paperclipai CLI and return parsed JSON.

    VERIFY before relying on this: the exact subcommand and flag names below
    are transcribed from the working examples in OPERATIONS.md
    (`paperclipai issue list -C <companyId> --api-key <key> --json`), not
    independently confirmed against `paperclipai --help` on the real host.
    Run that against the live CLI before trusting this in production — if
    flags differ, this is the only function that needs to change.
    """
    cmd = ["paperclipai", *args, "--api-key", os.environ["PAPERCLIP_API_KEY"], "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"paperclipai {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def list_review_candidates(company_id, project_id):
    issues = paperclip("issue", "list", "-C", company_id, "--project-id", project_id)
    return [i for i in issues if i.get("status") == "in_review"]


def find_repo_context(issue):
    """Best-effort: grep local repo git logs for a commit mentioning this
    issue's key (e.g. "RSA-42"). Returns a diff string or None.

    This is a heuristic, not a guarantee: nothing in OPERATIONS.md confirms
    that Paperclip issues carry an explicit repo/commit link, or that commit
    messages include the issue key. Treat a miss as normal, not an error.
    """
    key = issue.get("key") or issue.get("id") or ""
    if not key:
        return None
    for repo_path in REPO_MAP.values():
        if not os.path.isdir(repo_path):
            continue
        try:
            out = subprocess.run(
                ["git", "-C", repo_path, "log", f"--grep={key}", "-1", "-p"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout[:20000]  # cap for prompt size
        except Exception:
            continue
    return None


def build_review_prompt(issue, diff_context):
    comments = issue.get("comments", [])
    comment_text = "\n\n".join(
        f"[{c.get('author', '?')} @ {c.get('createdAt', '?')}]\n{c.get('body', '')}"
        for c in comments
    )
    parts = [
        "You are reviewing one unit of work from an autonomous engineering "
        "fleet before it reaches a human. You are advisory only: you cannot "
        "change status, merge, or push, and nothing you say auto-applies. "
        "Give a genuine second opinion, not a rubber stamp — the fleet's "
        "local model is known to sometimes fabricate a 'done' status, so "
        "check the actual evidence rather than trusting the narration.",
        f"## Issue\n{issue.get('title', '')}\n\n{issue.get('description', '')}",
        f"## Reported disposition and history\n{comment_text or '(no comments)'}",
    ]
    if diff_context:
        parts.append(f"## Matching commit found in the local repo\n```\n{diff_context}\n```")
    else:
        parts.append(
            "## No matching commit found\n"
            "No local commit matched this issue's key. Base your review only "
            "on the reported summary above, say so explicitly, and lower "
            "your confidence accordingly."
        )
    parts.append(
        "Respond in this exact structure:\n"
        "1. VERDICT: agree | disagree | needs-human-look\n"
        "2. CONFIDENCE: high | medium | low\n"
        "3. WHY: 2-4 sentences. If the diff contradicts the reported status "
        "(e.g. claimed done but the change looks incomplete, untested, or "
        "risky), say so directly.\n"
        "4. RISK FLAGS: any of {secrets, prohibited-path, scope-creep, "
        "untested, none}."
    )
    return "\n\n".join(parts)


def call_claude(prompt):
    import anthropic  # imported lazily so --dry-run works without the SDK installed

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_SUPERVISOR_MODEL", "claude-sonnet-5"),
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def file_approval_request(company_id, requested_by_agent_id, issue, review_text):
    """Record the review as a Paperclip approval request rather than a
    comment or status change — this is the one write primitive in
    OPERATIONS.md already confirmed to work from an agent-scoped key without
    granting that key board authority (agent keys get 403 on approve/reject,
    but Ram's own example shows an agent key CAN create the request)."""
    payload = json.dumps(
        {
            "summary": f"Claude Supervisor review of {issue.get('key', issue.get('id'))}: "
            f"{issue.get('title', '')}",
            "action": "claude_review",
            "review": review_text,
        }
    )
    cmd = [
        "paperclipai",
        "approval",
        "create",
        "-C",
        company_id,
        "--api-key",
        os.environ["PAPERCLIP_API_KEY"],
        "--type",
        "request_board_approval",
        "--requested-by-agent-id",
        requested_by_agent_id,
        "--payload",
        payload,
        "--json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"approval create failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def run_once(args, state):
    candidates = list_review_candidates(args.company_id, args.project_id)
    reviewed = state["reviewed_issue_updated_at"]
    new_reviews = 0
    for issue in candidates:
        key = issue.get("key") or issue.get("id")
        updated_at = issue.get("updatedAt", "")
        if reviewed.get(key) == updated_at:
            continue  # already reviewed this exact version of the issue
        print(f"[{datetime.datetime.now().isoformat()}] reviewing {key}: {issue.get('title', '')}")
        if args.dry_run:
            print("  (dry run: skipping Claude call and approval request)")
            continue
        diff_context = find_repo_context(issue)
        prompt = build_review_prompt(issue, diff_context)
        review_text = call_claude(prompt)
        file_approval_request(args.company_id, args.agent_id, issue, review_text)
        reviewed[key] = updated_at
        new_reviews += 1
    if not args.dry_run:
        save_state(state)
    print(f"done: {len(candidates)} candidate(s), {new_reviews} new review(s) filed")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company-id", dest="company_id", default=os.environ.get("PAPERCLIP_COMPANY_ID"))
    p.add_argument("--project-id", dest="project_id", default=os.environ.get("PAPERCLIP_PROJECT_ID"))
    p.add_argument(
        "--agent-id",
        dest="agent_id",
        default=os.environ.get("CLAUDE_SUPERVISOR_AGENT_ID"),
        help="claude-supervisor's own Paperclip agent id, used as --requested-by-agent-id",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.environ.get("POLL_INTERVAL_SECONDS", "300")),
        help="seconds between poll cycles in daemon mode (default 300 — deliberately slower "
        "than Paperclip's own ~30s heartbeat; see README.md on cost control)",
    )
    p.add_argument("--once", action="store_true", help="run a single pass and exit")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list review candidates but never call Claude or file an approval request",
    )
    args = p.parse_args()

    missing = [n for n in ("company_id", "project_id") if not getattr(args, n)]
    if missing:
        p.error(f"missing required config: {', '.join(missing)} (env or flag)")
    if not args.dry_run and not args.agent_id:
        p.error("--agent-id (or CLAUDE_SUPERVISOR_AGENT_ID) is required unless --dry-run")

    state = load_state()
    if args.once:
        run_once(args, state)
        return
    while True:
        try:
            run_once(args, state)
        except Exception as e:
            print(f"error during poll cycle: {e}", file=sys.stderr)
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
