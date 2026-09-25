"""Deterministic build gate, run right after Sam finishes and before any LLM reviewer looks.

Why (2026-09-24): Sam's first Mapepire change imported an npm package called `mapepire` that does
not exist (the real one is `@ibm/mapepire-js`). Unit tests that mock the client would pass, a
local-model QA agent would approve, and with merge-after-QA the result would land on main and
break CI. A compiler and a dependency resolver do not fall for confident prose, so they go first:

  dependencies  if package.json/package-lock.json changed: a real `npm install` in the worktree
                (its own node_modules, never the operator's), so a missing package fails HERE and
                the lockfile CI's `npm ci` needs is updated
  typecheck     the project's own type check
  tests         the project's own test suite; judged on FAILED TESTS, not the exit code, because
                main itself has one "no test suite in file" stub that makes vitest exit 1

A failed gate sends the issue straight back to Sam with the command output. Projects without a
configured gate are skipped (Claude review and QA still apply). Override or add a project with
PIPELINE_GATE_<PROJECT>='[{"name": "...", "cmd": "...", "timeout": 300}, ...]'.
"""
import json
import os
import pathlib
import subprocess
import tempfile

import pipeline_git as pg

DEFAULT_GATES = {
    "ibmimcp": [
        {"name": "dependencies", "kind": "npm-deps", "timeout": 600},
        {"name": "typecheck", "cmd": "npm run typecheck --silent", "timeout": 300},
        {"name": "tests", "kind": "vitest", "cmd": "npx --no-install vitest run --reporter=json --outputFile={out}",
         "timeout": 300},
    ],
}


def gate_steps(project):
    override = os.environ.get(f"PIPELINE_GATE_{(project or '').upper()}")
    if override:
        return json.loads(override)
    return DEFAULT_GATES.get((project or "").lower(), [])


def _sh(cmd, cwd, timeout):
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1"})
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


def _tail(text, n=1500):
    text = (text or "").strip()
    return text if len(text) <= n else "…" + text[-n:]


def _deps_step(step, wt):
    nm = pathlib.Path(wt) / "node_modules"
    if not nm.exists() and (pathlib.Path(wt) / "package.json").exists():
        # An agent deleted it (or the copy failed): restore it so typecheck/tests can run at all.
        rc, out = _sh("npm install --ignore-scripts --no-audit --no-fund", wt, step.get("timeout", 600))
        if rc != 0:
            return False, "node_modules was missing and `npm install` failed:\n" + _tail(out)
        return True, "node_modules was missing; reinstalled"
    base = pg.base_ref(wt, fetch=False)
    changed = pg.git("diff", "--name-only", f"{base}...HEAD", "--", "package.json", "package-lock.json", cwd=wt).stdout.split()
    changed += pg.git("status", "--porcelain", "--", "package.json", "package-lock.json", cwd=wt).stdout.split()
    if not changed:
        return True, "dependencies unchanged"
    if nm.is_symlink():
        nm.unlink()  # legacy worktrees only: never install through a link into the operator's node_modules
    rc, out = _sh("npm install --ignore-scripts --no-audit --no-fund", wt, step.get("timeout", 600))
    if rc != 0:
        return False, "npm install failed (a dependency does not exist or cannot be resolved):\n" + _tail(out)
    return True, "dependencies installed"


def _tests_step(step, wt):
    with tempfile.TemporaryDirectory() as t:
        out_file = os.path.join(t, "vitest.json")
        rc, out = _sh(step["cmd"].format(out=out_file), wt, step.get("timeout", 300))
        try:
            data = json.loads(pathlib.Path(out_file).read_text())
        except (OSError, ValueError):
            return False, "the test runner did not produce results:\n" + _tail(out)
    failed, passed = data.get("numFailedTests", 0), data.get("numPassedTests", 0)
    if failed:
        names = [f"{a.get('fullName') or a.get('title')}" for f in data.get("testResults", [])
                 for a in f.get("assertionResults", []) if a.get("status") == "failed"][:8]
        return False, f"{failed} test(s) failed ({passed} passed):\n  - " + "\n  - ".join(names)
    if not passed:
        return False, "no tests ran"
    return True, f"{passed} tests passed"


def run_gate(project, wt):
    """Run the project's gate in worktree `wt`. Returns
    {"ok", "ran", "failed" (step name or None), "summary", "detail", "lockfile_changed"}."""
    steps = gate_steps(project)
    if not steps:
        return {"ok": True, "ran": False, "failed": None, "summary": "no build gate configured", "detail": "",
                "lockfile_changed": False}
    done = []
    for step in steps:
        kind = step.get("kind")
        if kind == "npm-deps":
            ok, detail = _deps_step(step, wt)
        elif kind == "vitest":
            ok, detail = _tests_step(step, wt)
        else:
            rc, out = _sh(step["cmd"], wt, step.get("timeout", 300))
            ok, detail = rc == 0, ("ok" if rc == 0 else _tail(out))
        if not ok:
            return {"ok": False, "ran": True, "failed": step["name"], "detail": detail,
                    "summary": f"build gate FAILED at '{step['name']}'", "lockfile_changed": False}
        done.append(f"{step['name']}: {detail if kind else 'ok'}")
    lock = bool(pg.git("status", "--porcelain", "--", "package-lock.json", cwd=wt).stdout.strip())
    return {"ok": True, "ran": True, "failed": None, "detail": "", "lockfile_changed": lock,
            "summary": "build gate passed (" + "; ".join(done) + ")"}
