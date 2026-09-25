#!/usr/bin/env python3
"""Tests for pipeline_gate.py: real git worktrees, a fake `npm` on PATH, no network.

    cd scripts/setup/pipeline-advancer && python3 -m unittest -v test_pipeline_gate
"""
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import pipeline_gate as gate
import pipeline_git as pg

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


class GateFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        self.repo = t / "proj"
        run("init", "-q", "-b", "main", str(self.repo), cwd=t)
        (self.repo / "package.json").write_text(json.dumps({"name": "x", "dependencies": {"left-pad": "^1.0.0"}}))
        run("add", "-A", cwd=self.repo)
        run("commit", "-q", "-m", "init", cwd=self.repo)
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules" / "shared.txt").write_text("operator's node_modules")
        self.bin = t / "bin"
        self.bin.mkdir()
        self.npm_log = t / "npm.log"
        self.set_npm(0)
        p1 = mock.patch.object(pg, "worktree_root", lambda: t / "wt")
        p2 = mock.patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.wt = pg.create_worktree(self.repo, "RSA-7")["path"]

    def set_npm(self, rc, message=""):
        script = self.bin / "npm"
        script.write_text(f"#!/bin/sh\necho \"$@\" >> {self.npm_log}\n[ {rc} -ne 0 ] && echo '{message}' >&2\nexit {rc}\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

    def npm_calls(self):
        return self.npm_log.read_text().splitlines() if self.npm_log.exists() else []

    def commit(self, fname, text):
        (pathlib.Path(self.wt) / fname).write_text(text)
        run("add", "-A", cwd=self.wt)
        run("commit", "-q", "-m", "change", cwd=self.wt)


class ConfigTest(unittest.TestCase):
    def test_known_project_has_a_default_gate_and_unknown_has_none(self):
        self.assertEqual([s["name"] for s in gate.gate_steps("IBMiMCP")], ["dependencies", "typecheck", "tests"])
        self.assertEqual(gate.gate_steps("inova"), [])
        r = gate.run_gate("inova", "/nonexistent")
        self.assertTrue(r["ok"] and not r["ran"])

    def test_env_override_replaces_the_default(self):
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_INOVA": '[{"name": "lint", "cmd": "true"}]'}):
            self.assertEqual([s["name"] for s in gate.gate_steps("inova")], ["lint"])


class DependencyStepTest(GateFixture):
    steps = '[{"name": "dependencies", "kind": "npm-deps", "timeout": 30}]'

    def gate(self):
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_X": self.steps}):
            return gate.run_gate("x", self.wt)

    def test_unchanged_dependencies_skip_npm_entirely_and_keep_the_shared_node_modules(self):
        self.commit("src.ts", "export {}")
        r = self.gate()
        self.assertTrue(r["ok"])
        self.assertEqual(self.npm_calls(), [])
        self.assertTrue(os.path.islink(os.path.join(self.wt, "node_modules")))

    def test_a_dependency_that_does_not_exist_fails_the_gate_with_npms_own_message(self):
        """The production case: `mapepire` is not on npm."""
        self.commit("package.json", json.dumps({"name": "x", "dependencies": {"left-pad": "^1.0.0", "mapepire": "^0.1.0"}}))
        self.set_npm(1, "npm ERR! 404 Not Found - GET https://registry.npmjs.org/mapepire")
        r = self.gate()
        self.assertFalse(r["ok"])
        self.assertEqual(r["failed"], "dependencies")
        self.assertIn("registry.npmjs.org/mapepire", r["detail"])
        self.assertIn("does not exist", r["detail"])

    def test_changed_dependencies_get_their_own_node_modules_never_touching_the_operators(self):
        self.commit("package.json", json.dumps({"name": "x", "dependencies": {"left-pad": "^1.0.0", "ok-pkg": "^1.0.0"}}))
        r = self.gate()
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.npm_calls()), 1)
        self.assertIn("install --ignore-scripts", self.npm_calls()[0])
        self.assertFalse(os.path.islink(os.path.join(self.wt, "node_modules")))  # own install, not the shared symlink
        self.assertEqual((self.repo / "node_modules" / "shared.txt").read_text(), "operator's node_modules")

    def test_a_changed_lockfile_is_reported_so_it_gets_committed(self):
        self.commit("package.json", json.dumps({"name": "x", "dependencies": {"new": "^1.0.0"}}))
        (pathlib.Path(self.wt) / "package-lock.json").write_text("{}")  # what `npm install` would produce
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_X": self.steps}):
            r = gate.run_gate("x", self.wt)
        self.assertTrue(r["lockfile_changed"])


class TestsStepTest(GateFixture):
    def write_runner(self, payload, rc=0):
        script = pathlib.Path(self.tmp.name) / "runner.py"
        script.write_text(f"import sys, json\nopen(sys.argv[1], 'w').write(json.dumps({payload!r}))\nsys.exit({rc})\n")
        return json.dumps([{"name": "tests", "kind": "vitest", "cmd": f"python3 {script} {{out}}", "timeout": 30}])

    def gate(self, payload, rc=0):
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_X": self.write_runner(payload, rc)}):
            return gate.run_gate("x", self.wt)

    def test_all_passing_is_ok(self):
        r = self.gate({"numFailedTests": 0, "numPassedTests": 117})
        self.assertTrue(r["ok"])
        self.assertIn("117 tests passed", r["summary"])

    def test_judged_on_failed_tests_not_the_exit_code_because_main_has_a_stub_suite_that_exits_1(self):
        r = self.gate({"numFailedTests": 0, "numPassedTests": 117}, rc=1)  # exactly main's situation
        self.assertTrue(r["ok"])

    def test_failed_tests_fail_the_gate_and_are_named(self):
        r = self.gate({"numFailedTests": 2, "numPassedTests": 10, "testResults": [{"assertionResults": [
            {"status": "failed", "fullName": "mapepire connects over TLS"}, {"status": "passed", "fullName": "ok"}]}]})
        self.assertFalse(r["ok"])
        self.assertIn("2 test(s) failed", r["detail"])
        self.assertIn("mapepire connects over TLS", r["detail"])

    def test_no_tests_ran_or_no_results_file_fails_rather_than_passing_silently(self):
        self.assertFalse(self.gate({"numFailedTests": 0, "numPassedTests": 0})["ok"])
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_X": '[{"name": "tests", "kind": "vitest", "cmd": "true {out}"}]'}):
            r = gate.run_gate("x", self.wt)
        self.assertFalse(r["ok"])
        self.assertIn("did not produce results", r["detail"])


class CommandStepTest(GateFixture):
    def gate(self, steps):
        with mock.patch.dict(os.environ, {"PIPELINE_GATE_X": json.dumps(steps)}):
            return gate.run_gate("x", self.wt)

    def test_steps_run_in_order_and_stop_at_the_first_failure(self):
        marker = pathlib.Path(self.tmp.name) / "ran-third"
        r = self.gate([{"name": "a", "cmd": "true"}, {"name": "b", "cmd": "echo 'TS2307: Cannot find module mapepire' >&2; exit 2"},
                       {"name": "c", "cmd": f"touch {marker}"}])
        self.assertFalse(r["ok"])
        self.assertEqual(r["failed"], "b")
        self.assertIn("Cannot find module", r["detail"])
        self.assertFalse(marker.exists())

    def test_timeout_is_a_failure(self):
        r = self.gate([{"name": "slow", "cmd": "sleep 5", "timeout": 1}])
        self.assertFalse(r["ok"])
        self.assertIn("timed out", r["detail"])

    def test_all_green_summarises_every_step(self):
        r = self.gate([{"name": "a", "cmd": "true"}, {"name": "b", "cmd": "true"}])
        self.assertTrue(r["ok"])
        self.assertIn("a: ok", r["summary"])
        self.assertIn("b: ok", r["summary"])


if __name__ == "__main__":
    unittest.main()
