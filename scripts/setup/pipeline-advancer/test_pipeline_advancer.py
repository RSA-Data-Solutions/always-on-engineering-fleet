#!/usr/bin/env python3
"""Offline tests for the delivery pipeline: pipeline_advancer.py (routing) and claude_supervisor.py
(Claude spec/code/disposition reviews) driven against an in-memory fake Paperclip. Git operations
are faked here (pipeline_git.py has its own tests against real repos). No network, Claude or Slack.

    cd scripts/setup/pipeline-advancer && python3 -m unittest -v test_pipeline_advancer
"""
import datetime
import importlib.util
import itertools
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adv = load("pipeline_advancer", HERE / "pipeline_advancer.py")
sup = load("claude_supervisor", HERE.parent / "claude-supervisor" / "claude_supervisor.py")
pg = adv.pg

SAM, LYNN, AARON, RAM = adv.SAM_ID, adv.LYNN_ID, adv.AARON_ID, adv.RAM_ID
LONG_AGO = "2020-01-01T00:00:00Z"

SPEC_READY = (
    "1. VERDICT: ready\n2. PROJECT: IBMiMCP\n3. ENHANCED REQUEST:\n### Goal\nRetry the health check.\n"
    "### Acceptance criteria\n- [ ] retries 3 times\n4. QUESTIONS: none"
)
SPEC_UNKNOWN_PROJECT = SPEC_READY.replace("IBMiMCP", "unknown")
SPEC_UNCLEAR = "1. VERDICT: needs-clarification\n2. PROJECT: unknown\n3. ENHANCED REQUEST:\nn/a\n4. QUESTIONS:\n1. Which script?\n2. How many retries?"
CODE_APPROVE = (
    "1. VERDICT: approve\n2. CONFIDENCE: high\n3. WHY: Diff adds the retry loop.\n4. REWORK ITEMS: none\n"
    "5. TEST REQUESTS:\n1. Run deploy.sh with the server down; expect 3 retries.\n6. RISK FLAGS: none"
)
CODE_REWORK = (
    "1. VERDICT: rework\n2. CONFIDENCE: medium\n3. WHY: No backoff.\n4. REWORK ITEMS:\n1. Add backoff.\n"
    "5. TEST REQUESTS: none\n6. RISK FLAGS: untested"
)
CODE_UNSURE = "1. VERDICT: needs-human-look\n2. CONFIDENCE: low\n3. WHY: No diff.\n4. REWORK ITEMS: none\n5. TEST REQUESTS: none\n6. RISK FLAGS: untested"
CHECK_COMPLETE = "1. VERDICT: complete\n2. FAILURE TYPE: none\n3. EVIDENCE: 'all 12 tests passed'"
CHECK_FAILED_BUG = "1. VERDICT: failed\n2. FAILURE TYPE: code_bug\n3. EVIDENCE: 'retry never fires'"
CHECK_FAILED_ENV = "1. VERDICT: failed\n2. FAILURE TYPE: env_problem\n3. EVIDENCE: 'server would not start'"
CHECK_UNCLEAR = "1. VERDICT: unclear\n2. FAILURE TYPE: none\n3. EVIDENCE: only a plan was described"
SYSTEM_NEEDS_DISPOSITION = "Paperclip needs a disposition before this issue can continue."


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class FakePaperclip:
    """Just enough of Paperclip: issues, comments, and the write path (with its real validation)."""

    def __init__(self):
        self.issues, self.comments, self.slack = {}, {}, []
        self.ticks, self.ids = itertools.count(1), itertools.count(1)
        self.claude_replies = []

    def add_issue(self, title, description="", status="backlog", assignee=None, parent=None, updated=None):
        n = next(self.ids)
        issue = {
            "id": f"id-{n}", "identifier": f"RSA-{n}", "title": title, "description": description,
            "status": status, "assigneeAgentId": assignee, "parentId": parent, "statusVersion": 0,
            "createdAt": f"2026-01-01T00:00:{n:02d}Z", "updatedAt": updated or iso_now(),
            "executionRunId": None, "checkoutRunId": None,
        }
        self.issues[issue["id"]] = issue
        self.comments[issue["id"]] = []
        return issue

    def add_comment(self, issue_id, body, agent=None, system=False):
        c = {"id": f"c-{next(self.ticks)}", "body": body, "authorAgentId": agent,
             "authorType": "system" if system else ("agent" if agent else "user")}
        c["createdAt"] = f"2026-01-01T00:00:{c['id'].split('-')[1].zfill(6)}"
        self.comments[issue_id].append(c)

    def agent_finishes(self, issue_id, agent, status, comment):
        """What Sam/Lynn/Aaron do at the end of a run."""
        self.issues[issue_id].update(status=status)
        self.issues[issue_id]["statusVersion"] += 1
        self.add_comment(issue_id, comment, agent=agent)

    def agent_ends_silently(self, issue_id, agent, comment):
        """A local model that narrates but never sets a status: Paperclip blocks the issue."""
        self.agent_finishes(issue_id, agent, "blocked", comment)
        self.add_comment(issue_id, SYSTEM_NEEDS_DISPOSITION, system=True)

    def cli(self, *args):
        if args[:2] == ("issue", "list"):
            status = args[args.index("--status") + 1]
            return [dict(i) for i in self.issues.values() if i["status"] == status]
        if args[:2] == ("issue", "comments"):
            return [dict(c) for c in self.comments[args[2]]]
        if args[:2] == ("issue", "get"):
            return dict(self.issues[args[2]])
        raise AssertionError(f"unexpected CLI call {args}")

    def http_patch(self, issue_id, body):
        if body.get("status") == "blocked" and not body.get("unblockDescriptor"):
            raise RuntimeError("PATCH failed: 422 Entering blocked requires unresolved blockers, "
                               "a pending interaction/approval, or unblockDescriptor")
        issue = self.issues[issue_id]
        if "status" in body:
            issue["status"] = body["status"]
            issue["statusVersion"] += 1
        for src, dst in (("assigneeAgentId", "assigneeAgentId"), ("description", "description")):
            if src in body:
                issue[dst] = body[src]
        if "comment" in body:
            self.add_comment(issue_id, body["comment"])

    def post_slack(self, text, channel=None, thread_ts=None):
        self.slack.append({"text": text, "channel": channel, "thread_ts": thread_ts})

    def board_comment(self, issue_id, body):
        self.add_comment(issue_id, body)

    def call_claude(self, prompt):
        self.last_prompt = prompt
        return self.claude_replies.pop(0)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.fp = FakePaperclip()
        self.args = SimpleNamespace(company_id="co", dry_run=False)
        self.state = {k: {} for k in adv.STATE_KEYS}
        self.git_calls = []
        self.merge_result = {"status": "merged", "sha": "abcdef1234567890", "pushed": True, "note": ""}
        self.gate_result = {"ok": True, "ran": True, "failed": None, "detail": "", "lockfile_changed": False,
                            "summary": "build gate passed (typecheck: ok; tests: 117 tests passed)"}

        def create_worktree(repo, key):
            self.git_calls.append(("create_worktree", repo, key))
            return {"path": f"/wt/{key}", "branch": key.lower(), "base": "origin/main"}

        def merge_to_main(repo, branch, key, title, push=True):
            self.git_calls.append(("merge", branch, key, push))
            return self.merge_result

        patches = [
            mock.patch.object(adv, "paperclip", self.fp.cli),
            mock.patch.object(adv, "http_patch", self.fp.http_patch),
            mock.patch.object(adv, "post_slack", self.fp.post_slack),
            mock.patch.object(adv, "save_state", lambda s: None),
            mock.patch.object(adv, "SLACK_VERBOSE", False),
            mock.patch.object(adv, "MERGE_PUSH", True),
            mock.patch.object(pg, "repo_for_project", lambda p: "/repos/IBMiMCP" if p == "ibmimcp" else None),
            mock.patch.object(pg, "create_worktree", create_worktree),
            mock.patch.object(pg, "commit_worktree", lambda path, key, title: self.git_calls.append(("commit", key)) or "c0ffee1234"),
            mock.patch.object(pg, "merge_to_main", merge_to_main),
            mock.patch.object(adv.gate, "run_gate", lambda project, path: self.gate_result),
            mock.patch.object(pg, "cleanup_worktree", lambda repo, path, branch: self.git_calls.append(("cleanup", branch))),
            mock.patch.object(sup, "paperclip", self.fp.cli),
            mock.patch.object(sup, "post_board_comment", self.fp.board_comment),
            mock.patch.object(sup, "call_claude", self.fp.call_claude),
            mock.patch.object(sup, "find_pipeline_diff", lambda i, c: "diff --git a/deploy.sh b/deploy.sh"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.epic = self.fp.add_issue("Feature: retry", "Slack request\nSLACK_ORIGIN: channel=C0123ABC thread_ts=1700000000.000100")
        self.child = self.fp.add_issue("Add retry to health check", "Please add retries", parent=self.epic["id"])

    # -- helpers
    def claude(self, reply):
        self.fp.claude_replies.append(reply)
        sup.run_pipeline_reviews(self.args, time.monotonic())

    def advance(self, n=1):
        for _ in range(n):
            adv.run_once(self.args, self.state)

    def of(self, issue=None):
        return self.fp.issues[(issue or self.child)["id"]]

    @property
    def c(self):
        return self.of()

    def bodies(self, issue=None):
        return [x["body"] for x in self.fp.comments[(issue or self.child)["id"]]]

    def at(self, status, agent):
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), (status, agent))

    def to_sam(self):
        self.claude(SPEC_READY)
        self.advance()

    def sam_done_and_reviewed(self, verdict):
        self.fp.agent_finishes(self.child["id"], SAM, "done", "Fixed in commit abc1234")
        self.advance()
        self.claude(verdict)
        self.advance()

    def to_lynn(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_APPROVE)

    def merges(self):
        return [c for c in self.git_calls if c[0] == "merge"]

    # -- spec stage + worktree
    def test_spec_review_enhances_request_cuts_a_worktree_and_assigns_sam(self):
        self.to_sam()
        self.at("todo", SAM)
        self.assertIn("Retry the health check.", self.c["description"])
        self.assertEqual(self.git_calls, [("create_worktree", "/repos/IBMiMCP", "RSA-2")])
        handoff = next(b for b in self.bodies() if "handing to dev" in b)
        self.assertIn("Work ONLY in this git worktree", handoff)  # Sam is told exactly where to work...
        self.assertIn("`/wt/RSA-2`", handoff)  # ...as plain instructions, not just the machine tag
        self.assertIn("Do not touch any other checkout", handoff)
        self.assertIn("[pipeline-worktree: repo=/repos/IBMiMCP path=/wt/RSA-2 branch=rsa-2]", handoff)
        self.assertEqual(self.fp.slack, [])

    def test_unknown_project_blocks_for_a_human_instead_of_guessing_a_repo(self):
        self.claude(SPEC_UNKNOWN_PROJECT)
        self.advance()
        self.at("blocked", None)
        self.assertEqual(self.git_calls, [])
        self.assertEqual(len(self.fp.slack), 1)

    def test_worktree_failure_blocks_and_notifies(self):
        with mock.patch.object(pg, "create_worktree", side_effect=RuntimeError("git worktree add failed: boom")):
            self.claude(SPEC_READY)
            self.advance()
        self.at("blocked", None)
        self.assertIn("boom", self.fp.slack[0]["text"])

    def test_spec_clarification_blocks_and_notifies_once_then_rerun_works(self):
        self.claude(SPEC_UNCLEAR)
        self.advance()
        self.at("blocked", None)
        self.assertEqual(len(self.fp.slack), 1)
        self.assertIn("Which script?", self.fp.slack[0]["text"])
        self.advance()
        self.assertEqual(len(self.fp.slack), 1)
        self.of()["status"] = "backlog"  # answered -> back to backlog
        self.claude(SPEC_READY)
        self.advance()
        self.at("todo", SAM)

    # -- full path
    def test_full_happy_path_merges_after_lynn_then_publishes_to_the_origin_thread_and_closes(self):
        self.to_lynn()
        self.at("todo", LYNN)
        self.assertTrue(any("Run deploy.sh with the server down" in b for b in self.bodies()))
        self.assertTrue(any("/wt/RSA-2" in b and "Test in this worktree" in b for b in self.bodies()))
        self.assertIn(("commit", "RSA-2"), self.git_calls)  # safety-net commit before review
        self.assertEqual(self.merges(), [])  # NOT merged before Lynn approves

        self.fp.agent_finishes(self.child["id"], LYNN, "done", "5/5 tests passed")
        self.advance()
        self.assertEqual(self.merges(), [("merge", "rsa-2", "RSA-2", True)])  # merged (and pushed) only now
        self.at("todo", AARON)
        self.assertTrue(any("merged into `main` and pushed" in b and "Do NOT commit" in b for b in self.bodies()))

        self.fp.agent_finishes(self.child["id"], AARON, "done", "Deployed. health ok")
        self.advance()
        self.at("done", RAM)
        self.assertEqual(self.of(self.epic)["status"], "done")
        self.assertEqual(len(self.fp.slack), 1)
        msg = self.fp.slack[0]
        self.assertEqual((msg["channel"], msg["thread_ts"]), ("C0123ABC", "1700000000.000100"))
        for needle in ("Deployed. health ok", "5/5 tests passed", "abcdef12", "→ `main`"):
            self.assertIn(needle, msg["text"])
        self.assertIn(("cleanup", "rsa-2"), self.git_calls)
        before = (len(self.bodies()), len(self.fp.slack), len(self.git_calls))
        self.advance(2)  # idempotent
        self.assertEqual((len(self.bodies()), len(self.fp.slack), len(self.git_calls)), before)

    def test_final_result_falls_back_to_dm_without_slack_origin(self):
        self.of(self.epic)["description"] = "no origin recorded"
        self.to_lynn()
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "ok")
        self.advance()
        self.fp.agent_finishes(self.child["id"], AARON, "done", "Deployed")
        self.advance()
        self.assertEqual((self.fp.slack[0]["channel"], self.fp.slack[0]["thread_ts"]), (None, None))

    def test_merge_conflict_blocks_and_never_reaches_aaron(self):
        self.to_lynn()
        self.merge_result = {"status": "conflict", "detail": "CONFLICT (content): Merge conflict in deploy.sh"}
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "all pass")
        self.advance()
        self.at("blocked", None)
        self.assertIn("conflicts with main", self.fp.slack[0]["text"])
        self.assertFalse(self.state["merged"])

    def test_rejected_push_blocks_with_the_branch_left_for_a_pr(self):
        self.to_lynn()
        self.merge_result = {"status": "push_failed", "sha": "deadbeef00", "detail": "protected branch"}
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "all pass")
        self.advance()
        self.at("blocked", None)
        self.assertIn("protected branch", self.fp.slack[0]["text"])
        self.assertIn("open a PR", self.fp.slack[0]["text"])

    def test_a_merge_that_already_happened_is_not_repeated_if_a_later_step_retries(self):
        self.to_lynn()
        self.state["merged"][self.child["id"]] = "abcdef1234567890"
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "all pass")
        self.advance()
        self.assertEqual(self.merges(), [])
        self.at("todo", AARON)

    def test_legacy_issue_without_a_worktree_still_flows_without_a_merge(self):
        legacy = self.fp.add_issue("old", parent=self.epic["id"], status="done", assignee=LYNN)
        self.fp.add_comment(legacy["id"], "5/5 pass", agent=LYNN)
        self.advance()
        self.assertEqual((self.of(legacy)["status"], self.of(legacy)["assigneeAgentId"]), ("todo", AARON))
        self.assertEqual(self.merges(), [])

    def test_push_can_be_disabled(self):
        self.to_lynn()
        with mock.patch.object(adv, "MERGE_PUSH", False):
            self.fp.agent_finishes(self.child["id"], LYNN, "done", "ok")
            self.advance()
        self.assertEqual(self.merges(), [("merge", "rsa-2", "RSA-2", False)])

    # -- the deterministic build gate
    def test_a_failing_build_gate_sends_sam_back_with_the_output_and_skips_claude(self):
        self.to_sam()
        self.gate_result = {"ok": False, "ran": True, "failed": "dependencies", "lockfile_changed": False,
                            "summary": "gate FAILED", "detail": "npm ERR! 404 'mapepire@*' is not in this registry"}
        self.fp.agent_finishes(self.child["id"], SAM, "done", "implemented, all good")
        self.advance()
        self.at("todo", SAM)  # straight back: no Claude review of code that cannot build
        self.assertTrue(any("build gate FAILED at 'dependencies'" in b and "mapepire@*" in b and "rework 1/" in b
                            for b in self.bodies()))
        self.assertEqual(self.fp.slack, [])
        self.assertFalse(any("Claude code review" in b for b in self.bodies()))

    def test_a_passing_gate_is_recorded_for_the_reviewer_and_a_changed_lockfile_is_committed(self):
        self.to_sam()
        self.gate_result = {**self.gate_result, "lockfile_changed": True}
        self.fp.agent_finishes(self.child["id"], SAM, "done", "done")
        self.advance()
        self.assertTrue(any("build gate passed" in b and "117 tests passed" in b and "[pipeline-stage: code]" in b
                            for b in self.bodies()))
        self.assertEqual([c for c in self.git_calls if c[0] == "commit"], [("commit", "RSA-2"), ("commit", "RSA-2")])

    def test_a_crashing_gate_blocks_for_a_human_rather_than_waving_the_change_through(self):
        self.to_sam()
        self.fp.agent_finishes(self.child["id"], SAM, "done", "done")
        with mock.patch.object(adv.gate, "run_gate", side_effect=RuntimeError("npm not found")):
            self.advance()
        self.at("blocked", None)
        self.assertIn("build gate could not run", self.fp.slack[0]["text"])

    # -- rework loops
    def test_claude_rework_goes_back_to_sam_with_items_and_the_worktree_then_re_reviews(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_REWORK)
        self.at("todo", SAM)
        self.assertTrue(any("Add backoff." in b and "rework 1/" in b and "/wt/RSA-2" in b for b in self.bodies()))
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.at("todo", LYNN)

    def test_lynn_code_bug_goes_back_to_sam_then_through_claude_again(self):
        self.to_lynn()
        self.fp.agent_finishes(self.child["id"], LYNN, "blocked", "1 failed: classified as code_bug: retry never fires")
        self.advance()
        self.at("todo", SAM)
        self.assertTrue(any("retry never fires" in b for b in self.bodies()))
        self.assertEqual(self.merges(), [])
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.at("todo", LYNN)

    def test_lynn_env_problem_pauses_and_notifies_not_reworks(self):
        self.to_lynn()
        self.fp.agent_finishes(self.child["id"], LYNN, "blocked", "could not start server: env_problem")
        self.advance(2)
        self.at("blocked", LYNN)
        self.assertEqual(len(self.fp.slack), 1)

    def test_rework_is_capped_and_then_a_human_is_notified(self):
        with mock.patch.object(adv, "MAX_REWORK", 2):
            self.to_sam()
            for _ in range(2):
                self.sam_done_and_reviewed(CODE_REWORK)
                self.assertEqual(self.c["assigneeAgentId"], SAM)
            self.assertEqual(self.fp.slack, [])
            self.sam_done_and_reviewed(CODE_REWORK)  # third bounce exceeds the cap of 2
            self.at("blocked", None)
            self.assertIn("more than 2 times", self.fp.slack[0]["text"])

    def test_claude_cannot_verify_blocks_for_human(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_UNSURE)
        self.at("blocked", None)
        self.assertEqual(len(self.fp.slack), 1)

    def test_sam_blocked_notifies_and_pauses(self):
        self.to_sam()
        self.fp.agent_finishes(self.child["id"], SAM, "blocked", "cannot reproduce")
        self.advance(2)
        self.assertEqual(self.c["assigneeAgentId"], SAM)
        self.assertEqual(len(self.fp.slack), 1)

    # -- the per-agent queue (one llama slot => one pipeline issue per agent)
    def second_issue(self):
        epic2 = self.fp.add_issue("Feature: two", "SLACK_ORIGIN: none")
        return self.fp.add_issue("Second request", "please", parent=epic2["id"])

    def test_a_second_issue_waits_in_the_queue_while_sam_is_busy_and_starts_when_he_is_free(self):
        second = self.second_issue()
        self.to_sam()  # first -> Sam
        self.claude(SPEC_READY)  # second's spec
        self.advance()
        self.assertEqual((self.of(second)["status"], self.of(second)["assigneeAgentId"]), ("backlog", None))
        self.assertTrue(any("busy with RSA-2" in b and "queue-dev" in b for b in self.bodies(second)))
        self.advance(3)
        self.assertEqual(self.of(second)["status"], "backlog")  # still waiting
        self.fp.agent_finishes(self.child["id"], SAM, "done", "done")
        self.advance(2)  # first leaves Sam's hands; queue promotes the second
        self.assertEqual((self.of(second)["status"], self.of(second)["assigneeAgentId"]), ("todo", SAM))
        self.assertTrue(any("is free" in b for b in self.bodies(second)))

    def test_queue_is_first_in_first_out(self):
        second, third = self.second_issue(), self.second_issue()
        self.to_sam()
        self.claude(SPEC_READY)
        self.claude(SPEC_READY)
        self.advance()
        self.fp.agent_finishes(self.child["id"], SAM, "done", "done")
        self.advance(2)
        self.assertEqual(self.of(second)["assigneeAgentId"], SAM)
        self.assertEqual(self.of(third)["assigneeAgentId"], None)

    # -- silent runs: local models that finish without setting a status
    def test_silent_sam_goes_to_a_claude_disposition_check_and_a_complete_verdict_moves_on(self):
        self.to_sam()
        self.fp.agent_ends_silently(self.child["id"], SAM, "I implemented the retry loop and added tests.")
        self.advance()
        self.at("backlog", None)  # parked for Claude, no human involved
        self.assertEqual(self.fp.slack, [])
        self.claude(CHECK_COMPLETE)
        self.assertIn("Sam (engineer)", self.fp.last_prompt)
        self.advance()
        self.at("backlog", None)  # now waiting for the code review
        self.assertTrue(any("dev complete" in b and "[pipeline-stage: code]" in b for b in self.bodies()))
        self.assertIn(("commit", "RSA-2"), self.git_calls)
        self.claude(CODE_APPROVE)
        self.advance()
        self.at("todo", LYNN)

    def test_silent_lynn_with_a_code_bug_verdict_is_sent_back_to_sam(self):
        self.to_lynn()
        self.fp.agent_ends_silently(self.child["id"], LYNN, "Tests failed: retry never fires.")
        self.advance()
        self.claude(CHECK_FAILED_BUG)
        self.advance()
        self.at("todo", SAM)
        self.assertEqual(self.merges(), [])

    def test_silent_lynn_with_an_env_problem_pauses_for_a_human(self):
        self.to_lynn()
        self.fp.agent_ends_silently(self.child["id"], LYNN, "server would not start")
        self.advance()
        self.claude(CHECK_FAILED_ENV)
        self.advance()
        self.at("blocked", None)
        self.assertEqual(len(self.fp.slack), 1)

    def test_silent_lynn_complete_merges_and_hands_to_aaron(self):
        self.to_lynn()
        self.fp.agent_ends_silently(self.child["id"], LYNN, "12/12 passed incl. all requested checks")
        self.advance()
        self.claude(CHECK_COMPLETE)
        self.advance()
        self.assertEqual(len(self.merges()), 1)
        self.at("todo", AARON)

    def test_unclear_is_retried_once_then_a_human_is_told(self):
        self.to_sam()
        self.fp.agent_ends_silently(self.child["id"], SAM, "I will now begin...")
        self.advance()
        self.claude(CHECK_UNCLEAR)
        self.advance()
        self.at("todo", SAM)  # one retry, with an explicit instruction
        self.assertTrue(any("ended without setting a status" in b for b in self.bodies()))
        self.fp.agent_ends_silently(self.child["id"], SAM, "still just planning")
        self.advance()
        self.claude(CHECK_UNCLEAR)
        self.advance()
        self.at("blocked", None)
        self.assertEqual(len(self.fp.slack), 1)

    def test_an_agent_that_keeps_going_silent_is_eventually_escalated(self):
        self.to_sam()
        for _ in range(adv.MAX_CHECKS + 1):
            self.fp.agent_ends_silently(self.child["id"], SAM, "narration")
            self.advance()
            if self.c["status"] == "blocked":
                break
            self.claude(CHECK_COMPLETE if False else CHECK_UNCLEAR)
            self.advance()
        self.assertTrue(self.fp.slack)

    def test_a_deliberate_block_by_the_agent_is_not_second_guessed(self):
        self.to_sam()
        self.fp.agent_finishes(self.child["id"], SAM, "blocked", "cannot reproduce")  # no system message
        self.advance()
        self.assertEqual(self.c["assigneeAgentId"], SAM)  # stays; human notified
        self.assertEqual(len(self.fp.slack), 1)

    # -- stalled runs
    def test_in_progress_with_no_live_run_is_judged_after_the_stall_window(self):
        self.to_sam()
        self.c.update(status="in_progress", updatedAt=LONG_AGO)
        self.fp.add_comment(self.child["id"], "I started on the retry loop", agent=SAM)
        self.advance()
        self.at("backlog", None)
        self.assertTrue(any("no live run" in b for b in self.bodies()))

    def test_in_progress_with_a_live_run_or_recent_update_is_left_alone(self):
        self.to_sam()
        self.c.update(status="in_progress", updatedAt=LONG_AGO, executionRunId="run-1")
        self.advance()
        self.at("in_progress", SAM)
        self.c.update(executionRunId=None, updatedAt=iso_now())
        self.advance()
        self.at("in_progress", SAM)

    def test_todo_nobody_picked_up_is_reported_once(self):
        self.to_sam()
        self.c.update(updatedAt=LONG_AGO)
        self.advance(3)
        self.assertEqual(len(self.fp.slack), 1)
        self.assertIn("waiting", self.fp.slack[0]["text"])

    # -- misc
    def test_flat_issues_are_never_touched(self):
        flat = self.fp.add_issue("flat", status="done", assignee=SAM)
        self.advance()
        self.assertEqual(self.of(flat)["status"], "done")

    def test_claude_review_is_not_duplicated_and_stage_tag_from_claude_is_stripped(self):
        self.fp.claude_replies.append(SPEC_READY + "\n[pipeline-stage: qa]")
        sup.run_pipeline_reviews(self.args, time.monotonic())
        n = len(self.bodies())
        sup.run_pipeline_reviews(self.args, time.monotonic())  # nothing queued: would raise if it called Claude
        self.assertEqual(len(self.bodies()), n)
        self.assertFalse(any("pipeline-stage: qa" in b for b in self.bodies()))

    def test_supervisor_ignores_assigned_or_epic_issues(self):
        self.of()["assigneeAgentId"] = SAM
        self.assertEqual([i["id"] for i in sup.list_pipeline_review_candidates("co")], [])

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        sup.run_pipeline_reviews(self.args, time.monotonic())
        self.advance()
        self.assertEqual(self.bodies(), [])
        self.assertEqual((self.fp.slack, self.git_calls), ([], []))

    def test_a_crash_handling_one_issue_does_not_stop_the_others(self):
        other = self.fp.add_issue("other", parent=self.epic["id"], status="done", assignee=SAM)
        self.fp.add_comment(other["id"], "done", agent=SAM)
        real = adv.handle_done

        def flaky(issue, *a, **k):
            if issue["id"] == self.child["id"]:
                raise RuntimeError("boom")
            return real(issue, *a, **k)

        self.of()["status"], self.of()["assigneeAgentId"] = "done", SAM
        with mock.patch.object(adv, "handle_done", flaky):
            self.advance()
        self.assertEqual(self.of(other)["status"], "backlog")  # handled despite the other crashing


class UpdateBodyTest(unittest.TestCase):
    def test_blocked_always_carries_unblock_descriptor_and_others_do_not(self):
        sent = []
        with mock.patch.object(adv, "http_patch", lambda i, b: sent.append(b)):
            adv.update_issue("x", status="blocked", assignee=None, comment="c")
            adv.update_issue("x", status="todo", assignee=adv.SAM_ID)
            adv.update_issue("x", description="d")
        self.assertEqual(sent[0]["unblockDescriptor"]["owner"], "board")
        self.assertIsNone(sent[0]["assigneeAgentId"])
        self.assertNotIn("unblockDescriptor", sent[1])
        self.assertEqual(sent[2], {"description": "d"})


class RealGitDiffTest(unittest.TestCase):
    """The supervisor's worktree_diff against a real worktree made by pipeline_git."""

    def test_reviewer_sees_committed_and_uncommitted_changes_and_none_when_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            run = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, env=env)
            repo = t / "proj"
            run("init", "-q", "-b", "main", str(repo), cwd=t)
            (repo / "a.txt").write_text("1\n")
            run("add", "-A", cwd=repo)
            run("commit", "-q", "-m", "init", cwd=repo)
            with mock.patch.object(pg, "worktree_root", lambda: t / "wt"):
                wt = pg.create_worktree(repo, "RSA-9")["path"]
            self.assertIsNone(sup.worktree_diff(wt))  # nothing changed -> reviewer must say "no diff"
            (pathlib.Path(wt) / "a.txt").write_text("1\n2\n")
            run("commit", "-qam", "RSA-9: two", cwd=wt)
            (pathlib.Path(wt) / "a.txt").write_text("1\n2\n3\n")
            d = sup.worktree_diff(wt)
            self.assertIn("RSA-9: two", d)
            self.assertIn("+2", d)
            self.assertIn("UNCOMMITTED", d)
            self.assertIsNone(sup.worktree_diff(str(t / "gone")))


class DiffLookupTest(unittest.TestCase):
    """find_pipeline_diff's fallback (issue-key grep) against a real throwaway git repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        run = lambda *a: subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        check=True, capture_output=True, text=True)
        run("init", "-q", "-b", "main")
        for name, msg in (("a.txt", "RSA-24: real change"), ("b.txt", "RSA-240: different issue"), ("c.txt", "RSA-2: other")):
            pathlib.Path(self.repo, name).write_text(name)
            run("add", name)
            run("commit", "-q", "-m", msg)
        run("checkout", "-q", "-b", "fix/rsa-24-branch")
        pathlib.Path(self.repo, "d.txt").write_text("d")
        run("add", "d.txt")
        run("commit", "-q", "-m", "RSA-24: follow-up on a branch")
        run("checkout", "-q", "main")
        self.head = run("rev-parse", "HEAD").stdout.strip()
        p = mock.patch.object(sup, "REPO_MAP", {"t": self.repo})
        p.start()
        self.addCleanup(p.stop)

    def test_matches_whole_key_on_all_branches_only(self):
        out = sup.find_pipeline_diff.__wrapped__({"identifier": "RSA-24"}, []) if hasattr(sup.find_pipeline_diff, "__wrapped__") else None
        # find_pipeline_diff is mocked in PipelineTest only; here we call the real one
        real = load("claude_supervisor_real", HERE.parent / "claude-supervisor" / "claude_supervisor.py")
        real.REPO_MAP = {"t": self.repo}
        out = real.find_pipeline_diff({"identifier": "RSA-24"}, [])
        self.assertIn("RSA-24: real change", out)
        self.assertIn("follow-up on a branch", out)
        self.assertNotIn("RSA-240", out)
        self.assertNotIn("RSA-2: other", out)

    def test_finds_commit_hash_quoted_in_comments_and_miss_returns_none(self):
        real = load("claude_supervisor_real2", HERE.parent / "claude-supervisor" / "claude_supervisor.py")
        real.REPO_MAP = {"t": self.repo}
        self.assertIn("RSA-2: other", real.find_pipeline_diff({"identifier": "RSA-99"}, [{"body": f"done in {self.head[:10]}"}]))
        self.assertIsNone(real.find_pipeline_diff({"identifier": "RSA-99"}, [{"body": "nothing here"}]))


class ParsingTest(unittest.TestCase):
    def test_parse_field_and_section(self):
        t = "1. VERDICT: Approve\n5. TEST REQUESTS:\n1. a\n2. b\n6. RISK FLAGS: none"
        self.assertEqual(adv.parse_field(t, "verdict"), "approve")
        self.assertEqual(adv.parse_section(t, "test requests", ("risk flags",)), "1. a\n2. b")
        self.assertEqual(adv.parse_section(t, "nope"), "")

    def test_unparseable_verdict_defaults_to_the_safe_option(self):
        self.assertEqual(adv.pick_verdict("garbage", ("needs-human-look", "rework", "approve"), "needs-human-look"), "needs-human-look")
        self.assertEqual(adv.pick_verdict("garbage", ("complete", "failed", "unclear"), "unclear"), "unclear")

    def test_slack_origin(self):
        self.assertEqual(adv.slack_origin({"description": "x SLACK_ORIGIN: channel=D01ABC thread_ts=1.2"}), ("D01ABC", "1.2"))
        self.assertEqual(adv.slack_origin({"description": "SLACK_ORIGIN: thread_ts=1790059229.120989"}), (None, "1790059229.120989"))
        self.assertEqual(adv.slack_origin({"description": "SLACK_ORIGIN: none"}), (None, None))
        self.assertEqual(adv.slack_origin(None), (None, None))

    def test_missing_disposition_detection(self):
        sysmsg = {"authorType": "system", "body": SYSTEM_NEEDS_DISPOSITION}
        agent = {"authorAgentId": "a", "authorType": "agent", "body": "did stuff"}
        self.assertTrue(adv.missing_disposition([agent, sysmsg]))
        self.assertTrue(adv.missing_disposition([sysmsg]))  # agent produced nothing at all
        self.assertFalse(adv.missing_disposition([sysmsg, agent]))  # the agent spoke after the escalation
        self.assertFalse(adv.missing_disposition([agent]))

    def test_worktree_tag_roundtrip_uses_the_latest(self):
        a = adv.wt_tag("/r", {"path": "/w/1", "branch": "rsa-1"})
        b = adv.wt_tag("/r", {"path": "/w/2", "branch": "rsa-2"})
        self.assertEqual(adv.worktree_info([{"body": a}, {"body": "x"}, {"body": b}]), {"repo": "/r", "path": "/w/2", "branch": "rsa-2"})
        self.assertIsNone(adv.worktree_info([{"body": "no tag"}]))

    def test_age_minutes(self):
        self.assertGreater(adv.age_minutes(LONG_AGO), 1e6)
        self.assertLess(adv.age_minutes(iso_now()), 1)


if __name__ == "__main__":
    unittest.main()
