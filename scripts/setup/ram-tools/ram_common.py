"""Shared helpers for Ram's Slack-facing commands (ram-file, ram-status, ram-answer, ram-reply).

Why these exist (2026-09-24 review): Ram used to orchestrate Paperclip with free-form shell commands
(epic, copy an id, child; status via raw JSON). His model fabricated statuses, filed the same request
three times, and could not resume a paused issue. Each command here does one whole job
deterministically and prints a short, honest result.

How work flows (2026-09-30, "Ram routes" — no pipeline advancer or Claude supervisor): every request is
one parent issue assigned to Ram. Ram (in Paperclip) adds one child issue per stage
([dev] Sam -> [qa] Lynn -> merge -> [deploy] Aaron); a child going `done` wakes him for the next step.

Credentials come from ~/.hermes/.env (Ram's own Paperclip keys and the Slack bot token). The model never
types a key. Worker agents (inside a heartbeat run as anyone but Ram) are refused: these are Ram's tools.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

HOME = pathlib.Path.home()
HERMES_ENV = pathlib.Path(os.environ.get("RAM_HERMES_ENV", HOME / ".hermes" / ".env"))
COMPANY_ID = "f7aed163-5581-400d-8661-b8bbff78b849"
PROJECT_ID = "5f3f828f-4224-4ed7-b4d6-845f86a64d80"
RAM_ID = "297c5b1e-1025-4b33-b4f7-c53ef02fb24c"
API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api")

OPEN = ("backlog", "todo", "in_progress", "blocked", "in_review")
AGENTS = {
    "43bacfa8-1edd-4299-87c8-e2438ac3a572": "Sam", "fd64c507-364b-426b-b5d8-13a76f43142f": "Lynn",
    "26412e53-6692-4a6e-9a14-131cf7d6df05": "Aaron", "84997e0f-dbd1-4c0a-a2f6-b19a492cb43d": "Dhira",
    RAM_ID: "Ram",
}
ORIGIN_RE = re.compile(r"^ORIGIN:\s*slack\s+thread_ts=(\S+)", re.IGNORECASE | re.MULTILINE)


class RamError(Exception):
    pass


def refuse_in_worker():
    """Allowed from Slack (no run) and inside Ram's own Paperclip runs; refused for every other agent."""
    if os.environ.get("PAPERCLIP_RUN_ID") and os.environ.get("PAPERCLIP_AGENT_ID") != RAM_ID:
        raise RamError("this is one of Ram's tools; a worker agent must use its own task-bridge commands")


def env_value(path, name):
    try:
        for line in pathlib.Path(path).read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def ram_key():
    key = env_value(HERMES_ENV, "PAPERCLIP_RAM_STANDARD_KEY")
    if not key:
        raise RamError("PAPERCLIP_RAM_STANDARD_KEY is missing from ~/.hermes/.env")
    return key


def cli(*args):
    """paperclipai as Ram's standard identity. The .env URL ends in /api and the CLI adds its own, so
    never pass it through (that made every status check 404)."""
    env = {k: v for k, v in os.environ.items() if k != "PAPERCLIP_API_URL"}
    r = subprocess.run(["paperclipai", *args, "--api-key", ram_key(), "--json"], capture_output=True, text=True,
                       timeout=60, env=env)
    if r.returncode != 0:
        raise RamError(f"paperclipai {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return json.loads(r.stdout)


def open_issues():
    out = []
    for status in OPEN:
        out.extend(cli("issue", "list", "-C", COMPANY_ID, "--status", status))
    return out


def open_requests(issues=None):
    """Every unfinished request (a parent issue owned by Ram, no parent of its own), oldest first."""
    issues = open_issues() if issues is None else issues
    reqs = [i for i in issues if not i.get("parentId") and i.get("assigneeAgentId") == RAM_ID]
    return sorted(reqs, key=lambda i: i.get("createdAt") or "")


def current_stage(parent, issues):
    """The newest unfinished child of a request, or None."""
    kids = [i for i in issues if i.get("parentId") == parent["id"]]
    return sorted(kids, key=lambda i: i.get("createdAt") or "")[-1] if kids else None


def comments(issue_id):
    return sorted(cli("issue", "comments", issue_id), key=lambda c: c.get("createdAt") or "")


def resolve(ref):
    """RSA-30 or a uuid -> the issue."""
    return cli("issue", "get", ref)


def request_of(issue):
    """The request (top-level parent) an issue belongs to."""
    while issue.get("parentId"):
        issue = resolve(issue["parentId"])
    return issue


def where(parent, stage):
    if stage:
        who = AGENTS.get(stage.get("assigneeAgentId") or "", "unassigned")
        return f"{stage['title']} — {stage['status']} with {who}"
    if parent.get("status") in ("done", "cancelled"):
        return parent["status"]
    if parent.get("status") == "blocked":
        return "paused, waiting for your answer"
    return f"{parent['status']} with Ram (between stages)"


def wake_ram(issue_id, reason):
    """Ask Paperclip to start a Ram run on this issue (an agent may wake itself)."""
    body = {"source": "on_demand", "triggerDetail": "callback", "reason": reason, "payload": {"issueId": issue_id}}
    req = urllib.request.Request(f"{API_BASE}/agents/{RAM_ID}/wakeup", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {ram_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except Exception as e:  # the comment is already saved; a missed wake is recoverable
        raise RamError(f"the answer was saved but Ram could not be woken: {e}")


# ---- Slack (Ram's bot identity)
def slack_api(method, token, payload):
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RamError(f"Slack {method} failed: {parsed.get('error')}")
    return parsed


def post_slack(text, thread_ts=None):
    """Post to the requester's DM (SLACK_ALLOWED_USERS, single user), threaded when we know the thread."""
    token = env_value(HERMES_ENV, "SLACK_BOT_TOKEN")
    user = env_value(HERMES_ENV, "SLACK_ALLOWED_USERS").split(",")[0].strip()
    if not token or not user:
        raise RamError("SLACK_BOT_TOKEN or SLACK_ALLOWED_USERS is missing from ~/.hermes/.env")
    channel = slack_api("conversations.open", token, {"users": user})["channel"]["id"]
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return slack_api("chat.postMessage", token, payload)


def origin_thread(description):
    m = ORIGIN_RE.search(description or "")
    return m.group(1) if m else None


# ---- duplicate detection
_STOP = set("""a an the and or of to in on for with from by as at is are be this that it its into via
new add adds added support option feature request please make use using should would could need needs want
implement implementation create build fix change update do does not no yes""".split())


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9@/_.+-]{2,}", (text or "").lower()) if w not in _STOP}


def original_request(description):
    """The request text as filed: after the 'Request:' line, before any appended spec section."""
    text = (description or "").split("\n---\n")[0]
    m = re.search(r"^Request:\s*", text, re.MULTILINE)
    return text[m.end():] if m else text


def similarity(new_text, existing_text):
    """Overlap coefficient of significant words: |A∩B| / min(|A|,|B|). Robust to one side being much
    longer (an enhanced spec) — Jaccard would dilute it."""
    a, b = tokens(new_text), tokens(existing_text)
    if not a or not b:
        return 0.0, 0
    common = len(a & b)
    return common / min(len(a), len(b)), common


def find_duplicate(title, request, existing, threshold=0.45, min_common=6):
    # Calibrated on the real Mapepire duplicates (0.53-0.79 with 16-23 shared words) vs unrelated
    # requests (<=0.20, <=1 shared word) and related-but-different issues (0.35, 8 words).
    """The most similar unfinished request, or None."""
    best = None
    for i in existing:
        title_i = re.sub(r"^Feature:\s*", "", i.get("title", ""))
        score, common = similarity(f"{title} {request}", f"{title_i} {original_request(i.get('description'))}")
        if score >= threshold and common >= min_common and (best is None or score > best[0]):
            best = (score, i)
    return best[1] if best else None


def die(msg, code=1):
    print(json.dumps({"status": "error", "message": msg}))
    sys.exit(code)
