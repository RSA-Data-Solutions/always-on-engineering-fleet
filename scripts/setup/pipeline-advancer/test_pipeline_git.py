#!/usr/bin/env python3
"""Tests for pipeline_git.py against REAL git repos (a bare "origin" plus a clone in a temp
dir). No network. The operator's real repos are never touched.

    python3 -m unittest -v scripts/setup/pipeline-advancer/test_pipeline_git.py
"""
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import pipeline_git as pg

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def run(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        self.origin, self.repo = t / "origin.git", t / "proj"
        run("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=t)
        run("clone", "-q", str(self.origin), str(self.repo), cwd=t)
        run("checkout", "-q", "-b", "main", cwd=self.repo)
        (self.repo / "app.txt").write_text("line1\n")
        (self.repo / ".gitignore").write_text("node_modules/\n")
        run("add", "-A", cwd=self.repo)
        run("commit", "-q", "-m", "init", cwd=self.repo)
        run("push", "-q", "-u", "origin", "main", cwd=self.repo)
        self.root = t / "wt"
        p = mock.patch.object(pg, "worktree_root", lambda: self.root)
        p.start()
        self.addCleanup(p.stop)

    def origin_main(self):
        return run("rev-parse", "main", cwd=self.origin)


class WorktreeTest(GitFixture):
    def test_worktree_is_isolated_from_the_operators_checkout(self):
        run("checkout", "-q", "-b", "some-stale-feature-branch", cwd=self.repo)  # what happened in production
        (self.repo / "wip.txt").write_text("operator's uncommitted work")
        wt = pg.create_worktree(self.repo, "RSA-30")
        self.assertEqual(wt["branch"], "rsa-30")
        self.assertEqual(run("rev-parse", "--abbrev-ref", "HEAD", cwd=wt["path"]), "rsa-30")
        self.assertEqual(run("rev-parse", "HEAD", cwd=wt["path"]), self.origin_main())  # cut from main, not the stale branch
        self.assertFalse((pathlib.Path(wt["path"]) / "wip.txt").exists())  # operator's dirt did not leak in
        self.assertEqual(run("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo), "some-stale-feature-branch")  # untouched

    def test_idempotent_and_node_modules_is_shared(self):
        (self.repo / "node_modules").mkdir()
        a = pg.create_worktree(self.repo, "RSA-31")
        b = pg.create_worktree(self.repo, "RSA-31")
        self.assertEqual(a["path"], b["path"])
        self.assertTrue(os.path.islink(os.path.join(a["path"], "node_modules")))


class CommitTest(GitFixture):
    def test_safety_net_commits_real_work_but_not_report_litter_or_node_modules(self):
        (self.repo / "node_modules").mkdir()
        wt = pg.create_worktree(self.repo, "RSA-32")["path"]
        (pathlib.Path(wt) / "app.txt").write_text("line1\nmapepire\n")
        (pathlib.Path(wt) / "src").mkdir()
        (pathlib.Path(wt) / "src" / "mapepire.ts").write_text("export {}")
        for junk in ("FINAL_REPORT.md", "IMPLEMENTATION_SUMMARY.md", "fix-report-RSA-32.json", "implementation-summary.md"):
            (pathlib.Path(wt) / junk).write_text("litter")
        sha = pg.commit_worktree(wt, "RSA-32", "Add mapepire")
        self.assertTrue(sha)
        files = run("show", "--name-only", "--format=", "HEAD", cwd=wt).split()
        self.assertEqual(sorted(files), ["app.txt", "src/mapepire.ts"])
        self.assertEqual(run("log", "-1", "--format=%s", cwd=wt), "RSA-32: Add mapepire")

    def test_nothing_to_commit_returns_none(self):
        wt = pg.create_worktree(self.repo, "RSA-33")["path"]
        self.assertIsNone(pg.commit_worktree(wt, "RSA-33", "x"))
        self.assertEqual(pg.commits_ahead(wt), 0)

    def test_review_diff_shows_committed_and_uncommitted_work(self):
        wt = pg.create_worktree(self.repo, "RSA-34")["path"]
        (pathlib.Path(wt) / "app.txt").write_text("line1\nchange\n")
        pg.commit_worktree(wt, "RSA-34", "change")
        (pathlib.Path(wt) / "app.txt").write_text("line1\nchange\nmore\n")
        d = pg.diff_for_review(wt)
        self.assertIn("+change", d)
        self.assertIn("UNCOMMITTED", d)
        self.assertIn("RSA-34: change", d)


class MergeTest(GitFixture):
    def make_change(self, key, fname, text):
        wt = pg.create_worktree(self.repo, key)
        (pathlib.Path(wt["path"]) / fname).write_text(text)
        pg.commit_worktree(wt["path"], key, f"add {fname}")
        return wt

    def test_merge_pushes_to_origin_main_and_fast_forwards_local_main_without_touching_a_dirty_feature_checkout(self):
        wt = self.make_change("RSA-40", "new.txt", "hello")
        before = self.origin_main()
        run("checkout", "-q", "-b", "operators-branch", cwd=self.repo)
        (self.repo / "wip.txt").write_text("operator wip")
        r = pg.merge_to_main(self.repo, wt["branch"], "RSA-40", "Add new.txt")
        self.assertEqual(r["status"], "merged")
        self.assertTrue(r["pushed"])
        self.assertNotEqual(self.origin_main(), before)
        self.assertEqual(self.origin_main(), r["sha"])
        self.assertIn("RSA-40: Add new.txt", run("log", "-1", "--format=%B", "main", cwd=self.origin))
        self.assertEqual(run("rev-parse", "main", cwd=self.repo), r["sha"])  # local main follows
        self.assertEqual(run("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo), "operators-branch")  # checkout untouched
        self.assertTrue((self.repo / "wip.txt").exists())
        self.assertEqual(list((self.root / "_merge").glob("*")), [])  # throwaway worktree removed

    def test_when_main_is_checked_out_and_clean_it_is_fast_forwarded(self):
        wt = self.make_change("RSA-41", "n2.txt", "x")
        r = pg.merge_to_main(self.repo, wt["branch"], "RSA-41", "n2")
        self.assertEqual(r["status"], "merged")
        self.assertTrue((self.repo / "n2.txt").exists())  # working tree updated too

    def test_conflict_is_reported_and_leaves_main_untouched(self):
        wt = self.make_change("RSA-42", "app.txt", "from the branch\n")
        (self.repo / "app.txt").write_text("from main\n")
        run("commit", "-qam", "conflicting change on main", cwd=self.repo)
        run("push", "-q", "origin", "main", cwd=self.repo)
        before = self.origin_main()
        r = pg.merge_to_main(self.repo, wt["branch"], "RSA-42", "conflict")
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(self.origin_main(), before)

    def test_rejected_push_reports_push_failed_and_publishes_the_branch_for_a_pr(self):
        wt = self.make_change("RSA-43", "n3.txt", "x")
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nwhile read old new ref; do [ \"$ref\" = refs/heads/main ] && { echo 'protected branch' >&2; exit 1; }; done\nexit 0\n")
        hook.chmod(0o755)
        before = self.origin_main()
        r = pg.merge_to_main(self.repo, wt["branch"], "RSA-43", "n3")
        self.assertEqual(r["status"], "push_failed")
        self.assertEqual(self.origin_main(), before)
        self.assertIn("rsa-43", run("branch", "--list", "rsa-43", cwd=self.origin))  # branch pushed for a PR

    def test_push_disabled_merges_locally_only(self):
        wt = self.make_change("RSA-44", "n4.txt", "x")
        before = self.origin_main()
        r = pg.merge_to_main(self.repo, wt["branch"], "RSA-44", "n4", push=False)
        self.assertEqual((r["status"], r["pushed"]), ("merged", False))
        self.assertEqual(self.origin_main(), before)

    def test_cleanup_removes_worktree_and_merged_branch_but_never_an_unmerged_one(self):
        wt = self.make_change("RSA-45", "n5.txt", "x")
        pg.merge_to_main(self.repo, wt["branch"], "RSA-45", "n5")
        pg.cleanup_worktree(self.repo, wt["path"], wt["branch"])
        self.assertFalse(os.path.exists(wt["path"]))
        self.assertEqual(run("branch", "--list", "rsa-45", cwd=self.repo), "")
        wt2 = self.make_change("RSA-46", "n6.txt", "x")
        pg.cleanup_worktree(self.repo, wt2["path"], wt2["branch"])  # never merged
        self.assertIn("rsa-46", run("branch", "--list", "rsa-46", cwd=self.repo))  # work is not lost


class RepoLookupTest(unittest.TestCase):
    def test_unknown_and_missing_projects_are_none(self):
        self.assertIsNone(pg.repo_for_project("unknown"))
        self.assertIsNone(pg.repo_for_project(""))
        self.assertIsNone(pg.repo_for_project("nonexistent-project"))


if __name__ == "__main__":
    unittest.main()
