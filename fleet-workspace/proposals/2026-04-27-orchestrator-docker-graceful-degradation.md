# Proposal: iNova Orchestrator Graceful Degradation When Docker Unavailable

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-27
**Project:** iNova
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

The iNova orchestrator calls `docker.from_env()` at **module import
time** in `app/services/docker_mgr.py` (~line 13). Any environment
without a running Docker or Podman socket kills the process before it
binds any port, producing a silent `DockerException` crash. The service
reports HTTP 000 (connection refused) to health checks. This makes the
orchestrator impossible to run — even in read-only / diagnostic mode —
on machines that lack a container runtime.

## Evidence

- **inova#3** (filed 2026-04-26T07:17Z by msasikumar): Aaron's deploy
  report shows `health_check.status_code = 0` (connection refused).
  Root cause stated in the issue body: `docker.from_env()` at import
  time throws `DockerException: Error while fetching server API version`
  before any port is bound.
- The IBMiMCP sidecar on the same host was healthy (164 tools, HTTP 200)
  confirming the environment was otherwise functional — only the
  Docker socket was absent.

## Proposed change

**Type:** bug fix / resilience enhancement
**Name / identifier:** lazy Docker client initialisation

Move the `docker.from_env()` call inside the methods that actually need
a Docker client (e.g. `start_container`, `stop_container`). Wrap the
call in a try/except that raises a descriptive `ServiceUnavailableError`
rather than crashing the process. On startup, the orchestrator should
log a warning if Docker is unreachable but continue to serve non-Docker
routes (auth, config, IBM i MCP proxy, etc.).

```python
# Before (crashes at import time):
class DockerManager:
    def __init__(self):
        self.client = docker.from_env()   # ← kills process if no socket

# After (lazy, graceful):
class DockerManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = docker.from_env()
            except docker.errors.DockerException as exc:
                raise ServiceUnavailableError(
                    "Docker socket unavailable. Start Podman/Docker first."
                ) from exc
        return self._client
```

## Why this project is the right place for this

The crash is in iNova's own orchestrator code; the fix is entirely
contained within `app/services/docker_mgr.py`.

## Implementation notes

- File: `orchestrator/app/services/docker_mgr.py`, line ~13
- Also audit any other module-level `docker.*` calls in `app/`
- Add a `/api/health/docker` sub-check that returns `{"docker":
  "available"}` or `{"docker": "unavailable", "degraded": true}` so
  Aaron can distinguish partial-health from full failure
- No migration needed — pure Python refactor, no schema change

## Effort estimate

**Low** — ~20 lines changed in one file, plus a health sub-check (~15
lines). No new dependencies.

## Risk / caveats

- Routes that proxy container operations will now surface a 503 at
  request time rather than preventing startup; callers must handle 503.
- Review whether any test fixtures create the Docker client directly —
  if so, mock at the property level rather than `__init__`.
