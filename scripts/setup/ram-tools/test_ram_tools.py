#!/usr/bin/env python3
"""Tests for ram_common.py and the ram-file / ram-status / ram-answer / ram-reply commands (no network).

    cd scripts/setup/ram-tools && python3 -m unittest -v test_ram_tools
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ram_common as rc  # noqa: E402


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(HERE / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ram_file, ram_status, ram_answer, ram_reply = (load_script(n) for n in ("ram-file", "ram-status", "ram-answer", "ram-reply"))
SAM, AARON = "43bacfa8-1edd-4299-87c8-e2438ac3a572", "26412e53-6692-4a6e-9a14-131cf7d6df05"

MAPEPIRE_30 = {"identifier": "RSA-30", "id": "u30", "title": "Implement Mapepire connection adapter for IBMiMCP and iNovaIDE",
               "description": "Add Mapepire as a new connection type in both IBMiMCP and iNovaIDE, with configuration options for host, "
                              "port, and TLS settings. Should maintain compatibility with existing SSH/JDBC tooling. Mapepire is a modern "
                              "WebSocket-based API for IBM i connections.\n\n---\n## Enhanced request (Claude spec review)\nlots of spec text",
               "status": "in_progress", "assigneeAgentId": rc.RAM_ID, "parentId": None}
RETRY_4 = {"identifier": "RSA-4", "id": "u4", "title": "Add enhanced retry mechanism to IBMiMCP deploy script health-check step",
           "description": "Add a retry mechanism to the deploy script's health-check step to handle transient failures during deployment.",
           "status": "todo", "assigneeAgentId": rc.RAM_ID, "parentId": None}


def run_main(mod, argv):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["x", *argv]), redirect_stdout(out):
        try:
            mod.main()
        except SystemExit:
            pass
    text = out.getvalue().strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


class SimilarityTest(unittest.TestCase):
    """Calibrated on the real incident: the same Mapepire request was filed three times in different words."""

    def test_the_three_real_duplicates_are_caught(self):
        for title, req in (
            ("Implement Mapepire adapter for IBMiMCP", "Add Mapepire connection adapter to IBMiMCP. Mapepire is a modern WebSocket-based API for IBM i connections. It offers secure TLS connections and configuration options for host, port and TLS settings, alongside existing SSH/JDBC."),
            ("Implement Mapepire adapter for iNovaIDE", "Add Mapepire connection adapter to iNovaIDE. Mapepire is a modern WebSocket-based API for IBM i connections, new connection type with host, port, TLS settings, compatible with SSH/JDBC."),
            ("Implement Mapepire connection adapter for inovaide", "Add Mapepire as a new connection type to inovaide, which currently uses SSH/JDBC. Configuration options for host, port and TLS settings. Mapepire is a WebSocket-based API for IBM i connections."),
        ):
            self.assertEqual(rc.find_duplicate(title, req, [MAPEPIRE_30])["identifier"], "RSA-30", title)

    def test_unrelated_and_merely_related_requests_are_not_flagged(self):
        for title, req in (
            ("Fix README typo", "Fix the typo in the IBMiMCP README installation section, the word 'instalation'."),
            ("Dark mode", "Add a dark mode toggle to the iNova frontend settings page and persist the preference."),
            ("Stale jobs", "Investigate why the IBMiMCP listActiveJobs tool returns stale data after a job ends."),
            ("Retry", "Add a retry with backoff to the IBMiMCP deploy script health-check step."),
        ):
            self.assertIsNone(rc.find_duplicate(title, req, [MAPEPIRE_30]), title)

    def test_the_enhanced_spec_appended_to_an_existing_issue_does_not_dilute_matching(self):
        long_spec = dict(MAPEPIRE_30, description=MAPEPIRE_30["description"] + "\n" + "unrelated boilerplate " * 500)
        self.assertIsNotNone(rc.find_duplicate("Mapepire connection adapter", "Add Mapepire connection type for IBMiMCP with host, port, TLS settings alongside SSH/JDBC", [long_spec]))

    def test_picks_the_best_match(self):
        other = dict(RETRY_4, title="Mapepire notes", description="Mapepire connection adapter IBMiMCP")
        best = rc.find_duplicate("Implement Mapepire connection adapter for IBMiMCP", "Mapepire connection type host port TLS settings SSH/JDBC IBMiMCP iNovaIDE", [other, MAPEPIRE_30])
        self.assertEqual(best["identifier"], "RSA-30")


class FakeCli:
    """Records paperclipai calls; `issue create` returns a new issue."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "create"):
            return {"id": "uuid-new", "identifier": "RSA-41"}
        return {}

    def arg(self, call, flag):
        return call[call.index(flag) + 1]


class RamFileTest(unittest.TestCase):
    REQ = "Add a retry with exponential backoff to the IBMiMCP deploy script health check so transient failures do not fail a deploy."

    def setUp(self):
        self.cli, self.existing = FakeCli(), []
        os.environ.pop("PAPERCLIP_RUN_ID", None)
        for p in (mock.patch.object(rc, "cli", self.cli), mock.patch.object(rc, "open_issues", lambda: self.existing)):
            p.start()
            self.addCleanup(p.stop)

    def test_files_one_request_assigned_to_ram_with_the_slack_thread(self):
        r = run_main(ram_file, ["--title", "Deploy retry", "--request", self.REQ, "--thread", "1790.55"])
        self.assertEqual((r["status"], r["request"]), ("filed", "RSA-41"))
        (call,) = self.cli.calls
        self.assertEqual(self.cli.arg(call, "--assignee-agent-id"), rc.RAM_ID)  # wakes Ram in Paperclip
        self.assertEqual(self.cli.arg(call, "--project-id"), rc.PROJECT_ID)
        self.assertEqual(self.cli.arg(call, "--title"), "Feature: Deploy retry")
        desc = self.cli.arg(call, "--description")
        self.assertEqual(rc.origin_thread(desc), "1790.55")
        self.assertIn(self.REQ, desc)
        self.assertNotIn("--parent-id", call)

    def test_no_thread_still_records_a_slack_origin(self):
        run_main(ram_file, ["--title", "T", "--request", self.REQ])
        desc = self.cli.arg(self.cli.calls[0], "--description")
        self.assertTrue(desc.startswith("ORIGIN: slack\n"))
        self.assertIsNone(rc.origin_thread(desc))

    def test_a_similar_open_request_is_refused_and_nothing_is_created(self):
        self.existing = [MAPEPIRE_30]
        r = run_main(ram_file, ["--title", "Mapepire connection adapter", "--request",
                                "Add Mapepire as a connection type for IBMiMCP with host, port and TLS settings alongside SSH/JDBC"])
        self.assertEqual((r["status"], r["existing"]), ("duplicate", "RSA-30"))
        self.assertEqual(self.cli.calls, [])
        self.assertIn("--force", r["message"])

    def test_child_stage_issues_are_not_treated_as_requests(self):
        self.existing = [dict(MAPEPIRE_30, parentId="p1", assigneeAgentId=SAM)]
        r = run_main(ram_file, ["--title", "Mapepire connection adapter", "--request",
                                "Add Mapepire as a connection type for IBMiMCP with host, port and TLS settings alongside SSH/JDBC"])
        self.assertEqual(r["status"], "filed")

    def test_force_files_anyway(self):
        self.existing = [MAPEPIRE_30]
        r = run_main(ram_file, ["--title", "Mapepire", "--request", MAPEPIRE_30["description"][:200], "--force"])
        self.assertEqual(r["status"], "filed")

    def test_too_short_request_is_refused(self):
        self.assertEqual(run_main(ram_file, ["--title", "T", "--request", "do the thing"])["status"], "error")
        self.assertEqual(self.cli.calls, [])

    def test_a_worker_agent_is_refused_but_rams_own_run_is_allowed(self):
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "run-1", "PAPERCLIP_AGENT_ID": SAM}):
            self.assertEqual(run_main(ram_file, ["--title", "T", "--request", self.REQ])["status"], "error")
        self.assertEqual(self.cli.calls, [])
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "run-2", "PAPERCLIP_AGENT_ID": rc.RAM_ID}):
            self.assertEqual(run_main(ram_file, ["--title", "T", "--request", self.REQ])["status"], "filed")


class RamAnswerTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PAPERCLIP_RUN_ID", None)
        self.cli, self.wakes = FakeCli(), []
        self.parent = {"identifier": "RSA-31", "id": "u31", "status": "blocked", "parentId": None, "title": "Feature: t"}
        self.child = {"identifier": "RSA-32", "id": "u32", "status": "blocked", "parentId": "u31", "title": "[qa] t"}
        issues = {"RSA-31": self.parent, "u31": self.parent, "RSA-32": self.child}
        for p in (mock.patch.object(rc, "cli", self.cli), mock.patch.object(rc, "resolve", lambda ref: issues[ref]),
                  mock.patch.object(rc, "wake_ram", lambda iid, reason: self.wakes.append((iid, reason)))):
            p.start()
            self.addCleanup(p.stop)

    def test_the_answer_goes_on_the_request_and_wakes_ram(self):
        r = run_main(ram_answer, ["RSA-31", "inovaide is the same as inova; IBMiMCP first"])
        self.assertEqual((r["status"], r["request"]), ("answered", "RSA-31"))
        (call,) = self.cli.calls
        self.assertEqual(call[:3], ("issue", "update", "u31"))
        self.assertEqual(self.cli.arg(call, "--status"), "in_progress")
        self.assertIn("inovaide is the same as inova; IBMiMCP first", self.cli.arg(call, "--comment"))
        self.assertEqual(self.wakes, [("u31", "requester_answered")])

    def test_an_answer_naming_a_stage_issue_lands_on_its_request(self):
        run_main(ram_answer, ["RSA-32", "go on"])
        self.assertEqual(self.cli.calls[0][2], "u31")
        self.assertEqual(self.wakes[0][0], "u31")

    def test_finished_request_empty_answer_and_worker_are_refused(self):
        self.parent["status"] = "done"
        self.assertEqual(run_main(ram_answer, ["RSA-31", "x"])["status"], "error")
        self.parent["status"] = "blocked"
        self.assertEqual(run_main(ram_answer, ["RSA-31", "   "])["status"], "error")
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "r", "PAPERCLIP_AGENT_ID": SAM}):
            self.assertEqual(run_main(ram_answer, ["RSA-31", "x"])["status"], "error")
        self.assertEqual((self.cli.calls, self.wakes), ([], []))


class RamReplyTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PAPERCLIP_RUN_ID", None)
        self.cli, self.posts = FakeCli(), []
        self.parent = {"identifier": "RSA-31", "id": "u31", "status": "in_progress", "parentId": None,
                       "description": "ORIGIN: slack thread_ts=1790.55\nRequest: do it"}
        for p in (mock.patch.object(rc, "cli", self.cli), mock.patch.object(rc, "resolve", lambda ref: self.parent),
                  mock.patch.object(rc, "post_slack", lambda text, thread=None: self.posts.append((text, thread)))):
            p.start()
            self.addCleanup(p.stop)

    def test_posts_in_the_slack_thread_and_records_it_on_the_request(self):
        r = run_main(ram_reply, ["RSA-31", "Deployed and healthy."])
        self.assertEqual((r["status"], r["slack"]), ("sent", True))
        self.assertEqual(self.posts, [("RSA-31: Deployed and healthy.", "1790.55")])
        self.assertIn("Deployed and healthy.", self.cli.arg(self.cli.calls[0], "--comment"))

    def test_a_paperclip_only_request_gets_a_comment_and_no_slack_post(self):
        self.parent["description"] = "ORIGIN: paperclip\nRequest: do it"
        self.assertEqual(run_main(ram_reply, ["RSA-31", "done"])["slack"], False)
        self.assertEqual(self.posts, [])
        self.assertEqual(len(self.cli.calls), 1)

    def test_rams_own_run_may_reply(self):
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "r", "PAPERCLIP_AGENT_ID": rc.RAM_ID}):
            self.assertEqual(run_main(ram_reply, ["RSA-31", "hi"])["status"], "sent")


class RamStatusTest(unittest.TestCase):
    def test_lists_only_what_is_really_there_and_says_so_when_empty(self):
        with mock.patch.object(rc, "open_issues", lambda: []):
            self.assertIn("Nothing in flight", run_main(ram_status, []))
        dev = {"identifier": "RSA-50", "id": "u50", "title": "[dev] retry", "status": "in_progress",
               "assigneeAgentId": SAM, "parentId": "u4", "createdAt": "2"}
        paused = dict(MAPEPIRE_30, status="blocked")
        with mock.patch.object(rc, "open_issues", lambda: [paused, RETRY_4, dev]):
            out = run_main(ram_status, [])
        self.assertIn("2 unfinished", out)
        self.assertIn("RSA-30", out)
        self.assertIn("paused, waiting for your answer", out)
        self.assertIn("[dev] retry — in_progress with Sam", out)
        self.assertNotIn("RSA-50 ", out)  # stage issues are shown under their request, not as requests

    def test_detail_shows_stages_and_recent_history_by_who_said_it(self):
        cs = [{"body": "did the thing", "createdAt": "2026-09-24T10:00:00Z", "authorAgentId": SAM},
              {"body": "looks good", "createdAt": "2026-09-24T10:05:00Z", "authorType": "user"}]
        kids = [{"identifier": "RSA-51", "id": "u51", "title": "[dev] Mapepire", "status": "done", "assigneeAgentId": SAM,
                 "parentId": "u30", "createdAt": "1"}]
        with mock.patch.object(rc, "resolve", lambda r: MAPEPIRE_30), mock.patch.object(rc, "comments", lambda i: cs), \
                mock.patch.object(rc, "cli", lambda *a: kids):
            out = run_main(ram_status, ["RSA-30"])
        self.assertIn("Sam: did the thing", out)
        self.assertIn("RSA-51  [dev] Mapepire  —  done (Sam)", out)


class WhereTest(unittest.TestCase):
    def test_plain_english_locations(self):
        stage = {"title": "[deploy] x", "status": "in_progress", "assigneeAgentId": AARON}
        self.assertEqual(rc.where({"status": "in_progress"}, stage), "[deploy] x — in_progress with Aaron")
        self.assertEqual(rc.where({"status": "blocked"}, None), "paused, waiting for your answer")
        self.assertEqual(rc.where({"status": "todo"}, None), "todo with Ram (between stages)")
        self.assertEqual(rc.where({"status": "done"}, None), "done")


if __name__ == "__main__":
    unittest.main()
