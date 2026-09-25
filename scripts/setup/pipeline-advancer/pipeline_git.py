"""Git mechanics for the delivery pipeline (used by pipeline_advancer.py).

Why this exists (2026-09-24 review): every agent used to edit the ONE live checkout of a
project, which was sitting on a stale feature branch. Sam's uncommitted work was later
swept into an unrelated commit by Aaron and pushed to the wrong branch, so the code review
found "no diff". The fix is per-issue isolation, done deterministically here instead of
trusting a local model to run git correctly:

  create_worktree   one `git worktree` + branch per issue, cut from origin/main
  commit_worktree   safety-net commit of whatever Sam left uncommitted (minus report litter)
  merge_to_main     after QA approves: merge the branch into main in a throwaway worktree
                    (never touching the operator's checkout), push, and fast-forward the
                    local main. Production deploys are the operator's CI/CD, triggered by main.

Every function raises RuntimeError with git's own message on an unexpected failure and
returns a status dict for the *expected* failures (merge conflict, rejected push).
"""
import os
import pathlib
import re
import shutil
import subprocess

MAIN_BRANCH = os.environ.get("PIPELINE_MAIN_BRANCH", "main")

# Project name (Claude's spec review "PROJECT:" line) -> local repo. Override with
# PIPELINE_REPO_<NAME> (e.g. PIPELINE_REPO_IBMIMCP=/path).
_REPO_DEFAULTS = {
    "ibmimcp": "/home/sashi/Documents/projects/RSA/IBMiMCP",
    "inova": "/home/sashi/Documents/projects/RSA/inova",
    "fleet": "/home/sashi/Documents/projects/RSA/always-on-engineering-fleet",
}

# Files agents drop in the repo root as "reports" (from the old bug-N.json flow). They are
# never part of a change; keep them out of the safety-net commit.
JUNK_RE = re.compile(
    r"^(?:final[_-]report|implementation[_-]summary|fix-report[^/]*|[a-z0-9_-]*[_-]summary|"
    r"[a-z0-9_-]*[_-]report)\.(?:md|json|txt)$",
    re.IGNORECASE,
)

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Fleet Pipeline",
    "GIT_AUTHOR_EMAIL": "fleet-pipeline@localhost",
    "GIT_COMMITTER_NAME": "Fleet Pipeline",
    "GIT_COMMITTER_EMAIL": "fleet-pipeline@localhost",
    "GIT_TERMINAL_PROMPT": "0",
}


def repo_for_project(project):
    """Local repo path for a project name, or None if unknown."""
    name = (project or "").strip().lower()
    if not name or name == "unknown":
        return None
    override = os.environ.get(f"PIPELINE_REPO_{name.upper()}")
    path = override or _REPO_DEFAULTS.get(name)
    return path if path and os.path.isdir(os.path.join(path, ".git")) else None


def worktree_root():
    return pathlib.Path(os.environ.get("PIPELINE_WORKTREE_ROOT", str(pathlib.Path.home() / ".fleet-worktrees")))


def git(*args, cwd, timeout=60):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
        env={**os.environ, **_IDENTITY},
    )


def _must(result, what):
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed: {(result.stderr or result.stdout).strip()[:400]}")
    return result.stdout.strip()


def has_origin(repo):
    return git("remote", "get-url", "origin", cwd=repo).returncode == 0


def base_ref(repo, fetch=True):
    """origin/main if the repo has an origin (after a best-effort fetch), else main."""
    if has_origin(repo):
        if fetch:
            git("fetch", "origin", cwd=repo, timeout=120)  # offline is not fatal: use what we have
        if git("rev-parse", "--verify", "-q", f"origin/{MAIN_BRANCH}", cwd=repo).returncode == 0:
            return f"origin/{MAIN_BRANCH}"
    return MAIN_BRANCH


def create_worktree(repo, key):
    """Isolated worktree + branch for issue `key` (e.g. RSA-30), cut from the newest main.
    Idempotent: a second call returns the existing worktree. Returns {path, branch, base}."""
    repo = str(repo)
    branch = key.lower()
    path = worktree_root() / pathlib.Path(repo).name / key
    base = base_ref(repo)
    if path.exists() and git("rev-parse", "--is-inside-work-tree", cwd=path).returncode == 0:
        return {"path": str(path), "branch": branch, "base": base}
    path.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "prune", cwd=repo)
    if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=repo).returncode == 0:
        _must(git("worktree", "add", str(path), branch, cwd=repo), "git worktree add")
    else:
        _must(git("worktree", "add", "-b", branch, str(path), base, cwd=repo), "git worktree add")
    nm = pathlib.Path(repo) / "node_modules"
    if nm.is_dir() and not (path / "node_modules").exists():
        # An independent COPY (140 MB in ~0.15 s), never a symlink: through a symlink an agent's
        # `npm install` or `rm -rf node_modules/*` would modify or wipe the operator's real install.
        r = subprocess.run(["cp", "-a", "--reflink=auto", str(nm), str(path / "node_modules")], capture_output=True, text=True)
        if r.returncode != 0:
            shutil.copytree(nm, path / "node_modules", symlinks=True, dirs_exist_ok=True)
    return {"path": str(path), "branch": branch, "base": base}


def commit_worktree(path, key, title):
    """Safety net: commit whatever is uncommitted in the worktree (Sam is asked to commit
    himself, but a local model forgets). Excludes node_modules and report-litter files.
    Returns the new commit sha, or None if there was nothing to commit."""
    untracked = git("ls-files", "--others", "--exclude-standard", cwd=path).stdout.splitlines()
    junk = [f for f in untracked if "/" not in f and JUNK_RE.match(f)]
    # node_modules needs an explicit exclude only when it is OUR symlink to the shared install (a symlink
    # is not matched by .gitignore's `node_modules/`). A real directory (after the gate's own npm install)
    # is already ignored, and naming an ignored path in the pathspec makes `git add` fail.
    nm_symlink = os.path.islink(os.path.join(str(path), "node_modules"))
    spec = [".", *([":(exclude)node_modules"] if nm_symlink else []), *[f":(exclude){f}" for f in junk]]
    _must(git("add", "-A", "--", *spec, cwd=path), "git add")
    if git("diff", "--cached", "--quiet", cwd=path).returncode == 0:
        return None
    _must(git("commit", "-q", "-m", f"{key}: {title}", cwd=path), "git commit")
    return _must(git("rev-parse", "HEAD", cwd=path), "git rev-parse")


def commits_ahead(path, repo=None):
    base = base_ref(repo or path, fetch=False)
    out = git("rev-list", "--count", f"{base}..HEAD", cwd=path).stdout.strip()
    return int(out or 0)


def diff_for_review(path, max_chars=30000):
    """What the code reviewer sees: commits, stat and patch of the branch against main,
    plus any still-uncommitted changes."""
    base = base_ref(path, fetch=False)
    parts = [
        "$ git log --oneline " + base + "..HEAD\n" + git("log", "--oneline", f"{base}..HEAD", cwd=path).stdout,
        "$ git diff --stat " + base + "...HEAD\n" + git("diff", "--stat", f"{base}...HEAD", cwd=path).stdout,
        git("diff", f"{base}...HEAD", cwd=path).stdout,
    ]
    dirty = git("status", "--porcelain", "--untracked-files=no", cwd=path).stdout.strip()
    if dirty:
        parts.append("UNCOMMITTED CHANGES in the worktree:\n" + dirty + "\n" + git("diff", "HEAD", cwd=path).stdout)
    return "\n".join(parts)[:max_chars]


def _sync_local_main(repo, sha):
    """Fast-forward the repo's local `main` to sha without disturbing a dirty checkout.
    Returns a short note for the issue comment."""
    cur = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()
    if cur == MAIN_BRANCH:
        if git("status", "--porcelain", "--untracked-files=no", cwd=repo).stdout.strip():
            return f"local `{MAIN_BRANCH}` checkout has uncommitted changes, so it was NOT fast-forwarded"
        r = git("merge", "--ff-only", sha, cwd=repo)
        return "" if r.returncode == 0 else f"local `{MAIN_BRANCH}` could not fast-forward: {r.stderr.strip()[:200]}"
    if git("merge-base", "--is-ancestor", MAIN_BRANCH, sha, cwd=repo).returncode == 0:
        git("update-ref", f"refs/heads/{MAIN_BRANCH}", sha, cwd=repo)
        return ""
    return f"local `{MAIN_BRANCH}` has diverged from the merge; left as is"


def merge_to_main(repo, branch, key, title, push=True):
    """Merge `branch` into main after QA approval, in a throwaway worktree.
    Returns {"status": "merged"|"conflict"|"push_failed", "sha", "pushed", "detail", "note"}."""
    repo = str(repo)
    base = base_ref(repo)
    tmp = worktree_root() / "_merge" / key
    if tmp.exists():
        git("worktree", "remove", "--force", str(tmp), cwd=repo)
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "prune", cwd=repo)
    _must(git("worktree", "add", "--detach", str(tmp), base, cwd=repo), "git worktree add (merge)")
    try:
        msg = f"{key}: {title}\n\nMerged by the fleet pipeline after review and QA approval."
        m = git("merge", "--no-ff", "-m", msg, branch, cwd=tmp)
        if m.returncode != 0:
            git("merge", "--abort", cwd=tmp)
            return {"status": "conflict", "detail": (m.stdout + m.stderr).strip()[:600]}
        sha = _must(git("rev-parse", "HEAD", cwd=tmp), "git rev-parse")
        pushed = False
        if push and has_origin(repo):
            p = git("push", "origin", f"HEAD:{MAIN_BRANCH}", cwd=tmp, timeout=180)
            if p.returncode != 0:
                git("push", "origin", branch, cwd=repo, timeout=180)  # let a human open a PR
                return {"status": "push_failed", "sha": sha, "detail": p.stderr.strip()[:500]}
            pushed = True
            git("fetch", "origin", cwd=repo, timeout=120)
        return {"status": "merged", "sha": sha, "pushed": pushed, "note": _sync_local_main(repo, sha)}
    finally:
        git("worktree", "remove", "--force", str(tmp), cwd=repo)
        shutil.rmtree(tmp, ignore_errors=True)
        git("worktree", "prune", cwd=repo)


def cleanup_worktree(repo, path, branch):
    """Remove the issue's worktree, and its branch if (and only if) it is fully merged."""
    git("worktree", "remove", "--force", str(path), cwd=repo)
    shutil.rmtree(path, ignore_errors=True)
    git("worktree", "prune", cwd=repo)
    git("branch", "-d", branch, cwd=repo)  # -d refuses unmerged branches: never loses work
