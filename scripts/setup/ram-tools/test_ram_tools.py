#!/usr/bin/env python3
"""Tests for ram_common.py and the ram-file / ram-status / ram-answer commands (no network).

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


ram_file, ram_status, ram_answer = load_script("ram-file"), load_script("ram-status"), load_script("ram-answer")

MAPEPIRE_30 = {"identifier": "RSA-30", "id": "u30", "title": "Implement Mapepire connection adapter for IBMiMCP and iNovaIDE",
               "description": "Add Mapepire as a new connection type in both IBMiMCP and iNovaIDE, with configuration options for host, "
                              "port, and TLS settings. Should maintain compatibility with existing SSH/JDBC tooling. Mapepire is a modern "
                              "WebSocket-based API for IBM i connections.\n\n---\n## Enhanced request (Claude spec review)\nlots of spec text",
               "status": "todo", "assigneeAgentId": "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0", "parentId": "e1"}
RETRY_4 = {"identifier": "RSA-4", "id": "u4", "title": "Add enhanced retry mechanism to IBMiMCP deploy script health-check step",
           "description": "Add a retry mechanism to the deploy script's health-check step to handle transient failures during deployment.",
           "status": "todo", "assigneeAgentId": None, "parentId": "e2"}


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


class RamFileTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def bridge(*args):
            self.calls.append(args)
            n = len(self.calls)
            return {"id": f"uuid-{n}", "identifier": f"RSA-{40 + n}"}

        self.bridge = bridge
        patches = [mock.patch.object(ram_file, "bridge", bridge), mock.patch.object(rc, "open_children", lambda: self.existing),
                   mock.patch.object(rc, "comments", lambda i: []), mock.patch.dict(os.environ, {}, clear=False)]
        self.existing = []
        os.environ.pop("PAPERCLIP_RUN_ID", None)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    REQ = "Add a retry with exponential backoff to the IBMiMCP deploy script health check so transient failures do not fail a deploy."

    def test_files_epic_then_child_unassigned_in_backlog_with_the_slack_thread(self):
        r = run_main(ram_file, ["--title", "Deploy retry", "--request", self.REQ, "--thread", "1790.55"])
        self.assertEqual((r["status"], r["epic"], r["request"]), ("filed", "RSA-41", "RSA-42"))
        epic, child = self.calls
        self.assertIn("SLACK_ORIGIN: thread_ts=1790.55", epic[epic.index("--description") + 1])
        for call in (epic, child):
            self.assertIn("--unassigned", call)
            self.assertEqual(call[call.index("--status") + 1], "backlog")
        self.assertEqual(child[child.index("--parent-id") + 1], "uuid-1")  # child hangs off the epic just created
        self.assertNotIn("--assignee-agent-id", child)

    def test_no_thread_records_none(self):
        run_main(ram_file, ["--title", "T", "--request", self.REQ])
        self.assertIn("SLACK_ORIGIN: none", self.calls[0][self.calls[0].index("--description") + 1])

    def test_a_similar_open_request_is_refused_and_nothing_is_created(self):
        self.existing = [MAPEPIRE_30]
        r = run_main(ram_file, ["--title", "Mapepire connection adapter", "--request",
                                "Add Mapepire as a connection type for IBMiMCP with host, port and TLS settings alongside SSH/JDBC"])
        self.assertEqual((r["status"], r["existing"]), ("duplicate", "RSA-30"))
        self.assertEqual(self.calls, [])
        self.assertIn("--force", r["message"])

    def test_force_files_anyway(self):
        self.existing = [MAPEPIRE_30]
        r = run_main(ram_file, ["--title", "Mapepire", "--request", MAPEPIRE_30["description"][:200], "--force"])
        self.assertEqual(r["status"], "filed")

    def test_too_short_request_is_refused(self):
        r = run_main(ram_file, ["--title", "T", "--request", "do the thing"])
        self.assertEqual(r["status"], "error")
        self.assertEqual(self.calls, [])

    def test_if_the_child_fails_the_orphan_epic_is_reported_not_silently_retried(self):
        def flaky(*args):
            if "--parent-id" in args:
                raise rc.RamError("task-bridge failed: 403")
            return {"id": "uuid-e", "identifier": "RSA-41"}

        with mock.patch.object(ram_file, "bridge", flaky):
            r = run_main(ram_file, ["--title", "T", "--request", self.REQ])
        self.assertEqual(r["status"], "error")
        self.assertIn("RSA-41", r["message"])
        self.assertIn("do not retry blindly", r["message"])

    def test_a_worker_agent_is_refused(self):
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "run-1"}):
            r = run_main(ram_file, ["--title", "T", "--request", self.REQ])
        self.assertEqual(r["status"], "error")
        self.assertEqual(self.calls, [])


class RamAnswerTest(unittest.TestCase):
    def setUp(self):
        self.patched = []
        os.environ.pop("PAPERCLIP_RUN_ID", None)
        self.issue = {"identifier": "RSA-31", "id": "u31", "status": "blocked", "assigneeAgentId": None, "parentId": "e1", "title": "t"}
        self.cs = [{"body": "Pipeline: Claude needs clarification. [pipeline-stage: spec]", "createdAt": "1"}]
        for p in (mock.patch.object(rc, "resolve", lambda ref: self.issue), mock.patch.object(rc, "comments", lambda i: self.cs),
                  mock.patch.object(ram_answer, "patch", lambda iid, body: self.patches.append((iid, body)))):
            p.start()
            self.addCleanup(p.stop)
        self.patches = []

    def test_a_clarification_answer_is_posted_and_the_spec_review_is_rerun(self):
        r = run_main(ram_answer, ["RSA-31", "inovaide is the same as inova; IBMiMCP first"])
        self.assertEqual((r["status"], r["resumes_at"]), ("resumed", "spec"))
        iid, body = self.patches[0]
        self.assertEqual((iid, body["status"]), ("u31", "backlog"))
        self.assertIn("inovaide is the same as inova; IBMiMCP first", body["comment"])
        self.assertTrue(body["comment"].rstrip().endswith("[pipeline-stage: spec]"))

    def test_each_paused_stage_resumes_where_it_stopped(self):
        for tag, expect in (("code", "code"), ("dev", "queue-dev"), ("qa", "queue-qa"), ("deploy", "queue-deploy")):
            self.cs = [{"body": f"paused [pipeline-stage: {tag}]", "createdAt": "1"}]
            self.patches.clear()
            self.assertEqual(run_main(ram_answer, ["RSA-31", "go on"])["resumes_at"], expect)
            self.assertIn(f"[pipeline-stage: {expect}]", self.patches[0][1]["comment"])

    def test_refuses_anything_that_is_not_a_paused_pipeline_request(self):
        cases = {"flat issue": dict(self.issue, parentId=None), "not blocked": dict(self.issue, status="in_progress"),
                 "assigned to an agent": dict(self.issue, assigneeAgentId="ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0"),
                 "done": dict(self.issue, status="done")}
        for name, issue in cases.items():
            self.issue = issue
            self.patches.clear()
            self.assertEqual(run_main(ram_answer, ["RSA-31", "x"])["status"], "error", name)
            self.assertEqual(self.patches, [], name)

    def test_unknown_stage_and_empty_answer_and_worker_are_refused(self):
        self.cs = [{"body": "[pipeline-stage: bogus]", "createdAt": "1"}]
        self.assertEqual(run_main(ram_answer, ["RSA-31", "x"])["status"], "error")
        self.assertEqual(run_main(ram_answer, ["RSA-31", "   "])["status"], "error")
        with mock.patch.dict(os.environ, {"PAPERCLIP_RUN_ID": "r"}):
            self.assertEqual(run_main(ram_answer, ["RSA-31", "x"])["status"], "error")
        self.assertEqual(self.patches, [])


class RamStatusTest(unittest.TestCase):
    def test_lists_only_what_is_really_there_and_says_so_when_empty(self):
        with mock.patch.object(rc, "open_children", lambda: []):
            self.assertIn("Nothing in flight", run_main(ram_status, []))
        blocked = dict(MAPEPIRE_30, status="blocked", assigneeAgentId=None)
        with mock.patch.object(rc, "open_children", lambda: [blocked, dict(RETRY_4, status="todo", assigneeAgentId="ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0")]), \
                mock.patch.object(rc, "comments", lambda i: [{"body": "[pipeline-stage: code]", "createdAt": "1"}] if i == "u30" else []):
            out = run_main(ram_status, [])
        self.assertIn("2 unfinished", out)
        self.assertIn("RSA-30", out)
        self.assertIn("paused, waiting for you (stage: code)", out)
        self.assertIn("todo with Sam", out)

    def test_detail_shows_recent_history_by_who_said_it(self):
        cs = [{"body": "did the thing", "createdAt": "2026-09-24T10:00:00Z", "authorAgentId": "ba0e2a1d-45ad-4cfd-8c57-91927e5b4ab0"},
              {"body": "Pipeline: handing over", "createdAt": "2026-09-24T10:05:00Z", "authorType": "user"}]
        with mock.patch.object(rc, "resolve", lambda r: MAPEPIRE_30), mock.patch.object(rc, "comments", lambda i: cs):
            out = run_main(ram_status, ["RSA-30"])
        self.assertIn("Sam: did the thing", out)
        self.assertIn("RSA-30", out)


class WhereTest(unittest.TestCase):
    def test_plain_english_locations(self):
        self.assertEqual(rc.where(dict(status="backlog", assigneeAgentId=None), "spec"), "in Claude's spec review")
        self.assertEqual(rc.where(dict(status="backlog", assigneeAgentId=None), "queue-dev"), "queued for the next free agent")
        self.assertEqual(rc.where(dict(status="in_progress", assigneeAgentId="a02a6b9e-4d44-4f46-b373-83c15e6309c0"), "deploy"), "in_progress with Aaron")


if __name__ == "__main__":
    unittest.main()
