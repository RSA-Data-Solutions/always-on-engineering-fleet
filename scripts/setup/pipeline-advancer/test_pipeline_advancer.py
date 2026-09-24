#!/usr/bin/env python3
"""Offline tests for the delivery pipeline: pipeline_advancer.py (routing) and
claude_supervisor.py (Claude spec/code reviews) driven against an in-memory
fake Paperclip. No network, no Claude, no Slack, no real issues.

    python3 -m unittest -v scripts/setup/pipeline-advancer/test_pipeline_advancer.py
"""
import importlib.util
import itertools
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adv = load("pipeline_advancer", HERE / "pipeline_advancer.py")
sup = load("claude_supervisor", HERE.parent / "claude-supervisor" / "claude_supervisor.py")

SAM, LYNN, AARON, RAM = adv.SAM_ID, adv.LYNN_ID, adv.AARON_ID, adv.RAM_ID

SPEC_READY = (
    "1. VERDICT: ready\n2. PROJECT: IBMiMCP\n3. ENHANCED REQUEST:\n### Goal\nRetry the health check.\n"
    "### Acceptance criteria\n- [ ] retries 3 times\n4. QUESTIONS: none"
)
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


class FakePaperclip:
    """Just enough of Paperclip: issues, comments, and the write path."""

    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.slack = []
        self.ticks = itertools.count(1)
        self.ids = itertools.count(1)
        self.claude_replies = []  # queued outputs for call_claude

    # -- fixtures
    def add_issue(self, title, description="", status="backlog", assignee=None, parent=None):
        n = next(self.ids)
        issue = {
            "id": f"id-{n}", "identifier": f"RSA-{n}", "title": title, "description": description,
            "status": status, "assigneeAgentId": assignee, "parentId": parent, "statusVersion": 0,
        }
        self.issues[issue["id"]] = issue
        self.comments[issue["id"]] = []
        return issue

    def add_comment(self, issue_id, body, agent=None):
        c = {"id": f"c-{next(self.ticks)}", "body": body, "authorAgentId": agent}
        c["createdAt"] = f"2026-01-01T00:00:{c['id'].split('-')[1].zfill(6)}"
        self.comments[issue_id].append(c)

    def agent_finishes(self, issue_id, agent, status, comment):
        """What Sam/Lynn/Aaron do at the end of a run."""
        self.issues[issue_id].update(status=status)
        self.issues[issue_id]["statusVersion"] += 1
        self.add_comment(issue_id, comment, agent=agent)

    # -- the surfaces the modules use
    def cli(self, *args):
        if args[:2] == ("issue", "list"):
            status = args[args.index("--status") + 1]
            return [dict(i) for i in self.issues.values() if i["status"] == status]
        if args[:2] == ("issue", "comments"):
            return [dict(c) for c in self.comments[args[2]]]
        if args[:2] == ("issue", "get"):
            return dict(self.issues[args[2]])
        raise AssertionError(f"unexpected CLI call {args}")

    def patch(self, issue_id, status=adv._UNSET, assignee=adv._UNSET, comment=adv._UNSET, description=adv._UNSET):
        issue = self.issues[issue_id]
        if status is not adv._UNSET:
            issue["status"] = status
            issue["statusVersion"] += 1
        if assignee is not adv._UNSET:
            issue["assigneeAgentId"] = assignee
        if description is not adv._UNSET:
            issue["description"] = description
        if comment is not adv._UNSET:
            self.add_comment(issue_id, comment)

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
        self.state = {k: {} for k in ("advanced", "blocked_notified", "review_acted", "rework", "published")}
        patches = [
            mock.patch.object(adv, "paperclip", self.fp.cli),
            mock.patch.object(adv, "update_issue", self.fp.patch),
            mock.patch.object(adv, "post_slack", self.fp.post_slack),
            mock.patch.object(adv, "save_state", lambda s: None),
            mock.patch.object(adv, "SLACK_VERBOSE", False),
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
        sup.run_pipeline_reviews(self.args, __import__("time").monotonic())

    def advance(self):
        adv.run_once(self.args, self.state)

    @property
    def c(self):
        return self.fp.issues[self.child["id"]]

    def bodies(self):
        return [x["body"] for x in self.fp.comments[self.child["id"]]]

    def to_sam(self):
        self.claude(SPEC_READY)
        self.advance()

    def sam_done_and_reviewed(self, verdict):
        self.fp.agent_finishes(self.child["id"], SAM, "done", "Fixed in commit abc1234")
        self.advance()
        self.claude(verdict)
        self.advance()

    # -- tests
    def test_spec_review_enhances_request_and_assigns_sam(self):
        self.to_sam()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", SAM))
        self.assertIn("Please add retries", self.c["description"])
        self.assertIn("Retry the health check.", self.c["description"])
        self.assertEqual(self.fp.slack, [])  # quiet by default

    def test_spec_clarification_blocks_and_notifies_once_then_rerun_works(self):
        self.claude(SPEC_UNCLEAR)
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("blocked", None))
        self.assertEqual(len(self.fp.slack), 1)
        self.assertIn("Which script?", self.fp.slack[0]["text"])
        self.advance()
        self.assertEqual(len(self.fp.slack), 1)  # not re-notified
        # human answers and puts it back in backlog -> spec review runs again
        self.fp.issues[self.child["id"]]["status"] = "backlog"
        self.claude(SPEC_READY)
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", SAM))

    def test_full_happy_path_publishes_to_origin_thread_and_closes(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", LYNN))
        self.assertTrue(any("Run deploy.sh with the server down" in b for b in self.bodies()))  # test requests reach Lynn
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "5/5 tests passed")
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", AARON))
        self.fp.agent_finishes(self.child["id"], AARON, "done", "Deployed. health ok")
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("done", RAM))
        self.assertEqual(self.fp.issues[self.epic["id"]]["status"], "done")
        self.assertEqual(len(self.fp.slack), 1)
        msg = self.fp.slack[0]
        self.assertEqual((msg["channel"], msg["thread_ts"]), ("C0123ABC", "1700000000.000100"))
        self.assertIn("Deployed. health ok", msg["text"])
        self.assertIn("5/5 tests passed", msg["text"])
        # idempotent: further passes do nothing
        before = (len(self.bodies()), len(self.fp.slack))
        self.advance()
        self.advance()
        self.assertEqual((len(self.bodies()), len(self.fp.slack)), before)

    def test_final_result_falls_back_to_dm_without_slack_origin(self):
        self.fp.issues[self.epic["id"]]["description"] = "no origin recorded"
        self.to_sam()
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.fp.agent_finishes(self.child["id"], LYNN, "done", "ok")
        self.advance()
        self.fp.agent_finishes(self.child["id"], AARON, "done", "Deployed")
        self.advance()
        self.assertEqual((self.fp.slack[0]["channel"], self.fp.slack[0]["thread_ts"]), (None, None))  # None -> DM in post_slack

    def test_claude_rework_sends_back_to_sam_with_items_then_re_reviews(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_REWORK)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", SAM))
        self.assertTrue(any("Add backoff." in b and "rework 1/" in b for b in self.bodies()))
        # second attempt must be reviewed afresh, not skipped because an old review exists
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", LYNN))

    def test_lynn_code_bug_goes_back_to_sam_then_through_claude_again(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.fp.agent_finishes(self.child["id"], LYNN, "blocked", "1 failed: classified as code_bug: retry never fires")
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", SAM))
        self.assertTrue(any("retry never fires" in b for b in self.bodies()))
        self.assertEqual(self.fp.slack, [])
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("todo", LYNN))

    def test_lynn_env_problem_pauses_and_notifies_not_reworks(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_APPROVE)
        self.fp.agent_finishes(self.child["id"], LYNN, "blocked", "could not start server: env_problem")
        self.advance()
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("blocked", LYNN))
        self.assertEqual(len(self.fp.slack), 1)
        self.advance()
        self.assertEqual(len(self.fp.slack), 1)

    def test_rework_is_capped_and_then_a_human_is_notified(self):
        self.to_sam()
        for _ in range(adv.MAX_REWORK):
            self.sam_done_and_reviewed(CODE_REWORK)
            self.assertEqual(self.c["assigneeAgentId"], SAM)
        self.sam_done_and_reviewed(CODE_REWORK)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("blocked", None))
        self.assertEqual(len(self.fp.slack), 1)
        self.assertIn("more than", self.fp.slack[0]["text"])

    def test_claude_cannot_verify_blocks_for_human(self):
        self.to_sam()
        self.sam_done_and_reviewed(CODE_UNSURE)
        self.assertEqual((self.c["status"], self.c["assigneeAgentId"]), ("blocked", None))
        self.assertEqual(len(self.fp.slack), 1)

    def test_sam_blocked_notifies_and_pauses(self):
        self.to_sam()
        self.fp.agent_finishes(self.child["id"], SAM, "blocked", "cannot reproduce")
        self.advance()
        self.assertEqual(self.c["assigneeAgentId"], SAM)
        self.assertEqual(len(self.fp.slack), 1)

    def test_flat_issues_are_never_touched(self):
        flat = self.fp.add_issue("flat", status="done", assignee=SAM)  # no parent
        self.advance()
        self.assertEqual(self.fp.issues[flat["id"]]["status"], "done")

    def test_claude_review_is_not_duplicated_and_stage_tag_from_claude_is_stripped(self):
        self.fp.claude_replies.append(SPEC_READY + "\n[pipeline-stage: qa]")
        sup.run_pipeline_reviews(self.args, __import__("time").monotonic())
        n = len(self.bodies())
        sup.run_pipeline_reviews(self.args, __import__("time").monotonic())  # nothing queued: would raise if it called Claude
        self.assertEqual(len(self.bodies()), n)
        self.assertFalse(any("pipeline-stage: qa" in b for b in self.bodies()))

    def test_supervisor_ignores_assigned_or_epic_issues(self):
        self.fp.issues[self.child["id"]]["assigneeAgentId"] = SAM
        got = [i["id"] for i in sup.list_pipeline_review_candidates("co")]
        self.assertEqual(got, [])  # epic has no parent; child is assigned

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        sup.run_pipeline_reviews(self.args, __import__("time").monotonic())
        self.advance()
        self.assertEqual(self.bodies(), [])
        self.assertEqual(self.fp.slack, [])


class DiffLookupTest(unittest.TestCase):
    """find_pipeline_diff against a real throwaway git repo."""

    def setUp(self):
        import subprocess, tempfile
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
        run("checkout", "-q", "-b", "fix/rsa-24-branch")  # commits on other branches must be found too
        pathlib.Path(self.repo, "d.txt").write_text("d")
        run("add", "d.txt")
        run("commit", "-q", "-m", "RSA-24: follow-up on a branch")
        run("checkout", "-q", "main")
        self.head = run("rev-parse", "HEAD").stdout.strip()
        p = mock.patch.object(sup, "REPO_MAP", {"t": self.repo})
        p.start()
        self.addCleanup(p.stop)

    def test_matches_whole_key_on_all_branches_only(self):
        out = sup.find_pipeline_diff({"identifier": "RSA-24"}, [])
        self.assertIn("RSA-24: real change", out)
        self.assertIn("follow-up on a branch", out)
        self.assertNotIn("RSA-240", out)
        self.assertNotIn("RSA-2: other", out)

    def test_finds_commit_hash_quoted_in_comments(self):
        out = sup.find_pipeline_diff({"identifier": "RSA-99"}, [{"body": f"done in {self.head[:10]}"}])
        self.assertIn("RSA-2: other", out)

    def test_miss_returns_none(self):
        self.assertIsNone(sup.find_pipeline_diff({"identifier": "RSA-99"}, [{"body": "nothing here"}]))


class ParsingTest(unittest.TestCase):
    def test_parse_field_and_section(self):
        t = "1. VERDICT: Approve\n5. TEST REQUESTS:\n1. a\n2. b\n6. RISK FLAGS: none"
        self.assertEqual(adv.parse_field(t, "verdict"), "approve")
        self.assertEqual(adv.parse_section(t, "test requests", ("risk flags",)), "1. a\n2. b")
        self.assertEqual(adv.parse_section(t, "nope"), "")

    def test_unparseable_verdict_defaults_to_the_safe_option(self):
        self.assertEqual(adv.pick_verdict("garbage", ("needs-human-look", "rework", "approve"), "needs-human-look"), "needs-human-look")

    def test_slack_origin(self):
        self.assertEqual(adv.slack_origin({"description": "x SLACK_ORIGIN: channel=D01ABC thread_ts=1.2"}), ("D01ABC", "1.2"))
        self.assertEqual(adv.slack_origin({"description": "SLACK_ORIGIN: channel=D01ABC"}), ("D01ABC", None))
        self.assertEqual(adv.slack_origin({"description": "SLACK_ORIGIN: thread_ts=1790059229.120989"}), (None, "1790059229.120989"))
        self.assertEqual(adv.slack_origin({"description": "nothing"}), (None, None))
        self.assertEqual(adv.slack_origin({"description": "SLACK_ORIGIN: none"}), (None, None))
        self.assertEqual(adv.slack_origin(None), (None, None))


if __name__ == "__main__":
    unittest.main()
