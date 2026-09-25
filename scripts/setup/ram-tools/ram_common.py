"""Shared helpers for Ram's three Slack-facing commands (ram-file, ram-status, ram-answer).

Why these exist (2026-09-24 review): Ram used to orchestrate Paperclip with free-form shell commands
(epic, copy an id, child; status via raw JSON). His model fabricated statuses, filed the same request
three times, and could not resume a paused issue (his bridge key can't write to existing issues).
Each command here does one whole job deterministically and prints a short, honest result.

Credentials come from ~/.hermes/.env (Ram's own keys) and ~/.pipeline-advancer/.env (the board
workaround key, used ONLY by ram-answer for the two narrow writes it allows). The model never types a
key. Worker agents (PAPERCLIP_RUN_ID set = inside a heartbeat run) are refused: these are Ram's tools.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

HOME = pathlib.Path.home()
HERMES_ENV = pathlib.Path(os.environ.get("RAM_HERMES_ENV", HOME / ".hermes" / ".env"))
ADVANCER_ENV = pathlib.Path(os.environ.get("RAM_ADVANCER_ENV", HOME / ".pipeline-advancer" / ".env"))
COMPANY_ID = "0c265070-3974-497a-99ee-cf942ffe139d"
PROJECT_ID = "b9bb008e-7771-4bc7-aad8-71e2faa3307f"
API_BASE = os.environ.get("PAPERCLIP_API_BASE", "http://127.0.0.1:3100/api")
BRIDGE_SCRIPT = HOME / ".hermes" / "skills" / "paperclip-task-bridge" / "paperclip-task.mjs"
NODE = "/usr/local/bin/node"

STAGE_TAG_RE = re.compile(r"\[pipeline-stage:\s*([a-z-]+)\]", re.IGNORECASE)
OPEN = ("backlog", "todo", "in_progress", "blocked", "in_review")
AGENTS = {
    "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0": "Sam", "d053dfe0-dbd6-45fd-8069-32b51a00580e": "Lynn",
    "a02a6b9e-4d44-4f46-b373-83c15e6309c0": "Aaron", "db976f2e-e1ca-432f-b6b4-4aa2c5d302b1": "Dhira",
    "093a44a5-da1d-421a-9708-cd1f05e6d734": "Ram",
}


class RamError(Exception):
    pass


def refuse_in_worker():
    if os.environ.get("PAPERCLIP_RUN_ID"):
        raise RamError("this is one of Ram's tools; a worker agent must use its own task-bridge commands")


def env_value(path, name):
    try:
        for line in pathlib.Path(path).read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def cli(*args):
    """paperclipai as Ram's standard (read) identity. The .env URL ends in /api and the CLI adds its
    own, so never pass it through (that made every status check 404)."""
    key = env_value(HERMES_ENV, "PAPERCLIP_RAM_STANDARD_KEY")
    if not key:
        raise RamError("PAPERCLIP_RAM_STANDARD_KEY is missing from ~/.hermes/.env")
    env = {k: v for k, v in os.environ.items() if k != "PAPERCLIP_API_URL"}
    r = subprocess.run(["paperclipai", *args, "--api-key", key, "--json"], capture_output=True, text=True,
                       timeout=60, env=env)
    if r.returncode != 0:
        raise RamError(f"paperclipai {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return json.loads(r.stdout)


def open_children():
    """Every enrolled (has a parent) issue that is not finished, newest last."""
    out = []
    for status in OPEN:
        out.extend(i for i in cli("issue", "list", "-C", COMPANY_ID, "--status", status) if i.get("parentId"))
    return sorted(out, key=lambda i: i.get("createdAt") or "")


def comments(issue_id):
    return sorted(cli("issue", "comments", issue_id), key=lambda c: c.get("createdAt") or "")


def stage_of(cs):
    stage = "spec"
    for c in cs:
        m = STAGE_TAG_RE.search(c.get("body") or "")
        if m:
            stage = m.group(1).lower()
    return stage


def resolve(ref):
    """RSA-30 or a uuid -> the issue."""
    return cli("issue", "get", ref)


# ---- duplicate detection
_STOP = set("""a an the and or of to in on for with from by as at is are be this that it its into via
new add adds added support option feature request please make use using should would could need needs want
implement implementation create build fix change update do does not no yes""".split())


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9@/_.+-]{2,}", (text or "").lower()) if w not in _STOP}


def original_request(description):
    """The child's description before Claude's appended 'Enhanced request' section."""
    return (description or "").split("\n---\n")[0]


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
    """The most similar unfinished pipeline issue, or None."""
    best = None
    for i in existing:
        score, common = similarity(f"{title} {request}", f"{i.get('title', '')} {original_request(i.get('description'))}")
        if score >= threshold and common >= min_common and (best is None or score > best[0]):
            best = (score, i)
    return best[1] if best else None


def where(issue, stage):
    st = issue.get("status")
    who = AGENTS.get(issue.get("assigneeAgentId") or "", None)
    if st == "blocked" and not who:
        return f"paused, waiting for you (stage: {stage})"
    if who:
        return f"{st} with {who}"
    return {"spec": "in Claude's spec review", "code": "in Claude's code review"}.get(stage) or \
        ("queued for the next free agent" if stage.startswith("queue-") else f"{st} ({stage})")


def die(msg, code=1):
    print(json.dumps({"status": "error", "message": msg}))
    sys.exit(code)
