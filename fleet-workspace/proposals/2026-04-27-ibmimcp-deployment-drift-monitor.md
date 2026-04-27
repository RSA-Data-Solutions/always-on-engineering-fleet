# Proposal: IBMiMCP Cross-Environment Deployment Drift Monitor

**Proposed by:** Dhira (Research Agent)
**Date:** 2026-04-27
**Project:** iNova / IBMiMCP
**Priority:** High
**Status:** Awaiting CTO Review

## Problem

The IBMiMCP sidecar on the cloud server (`65.75.200.130`) ran silently
for 20+ days on a stale image that registered only 47 tools — less than
half the expected 130+. No alert fired. The drift was caught only when
Aaron's deployment gate happened to run during Routine 4. Operators
had no visibility into the mismatch between local-dev (164 tools),
homelab (164 tools), and cloud (47 tools) environments.

## Evidence

- **inova#4** (filed 2026-04-26T21:55Z by msasikumar): Aaron's
  deployment gate reported `registered_tool_count = 47` against a
  threshold of `>= 130`. Container uptime was ~1,777,175 s (~20.6 days).
  Probable cause: cloud image was never redeployed after the toolset
  expanded in April.
- Pattern: this is the second deployment gate failure in two days
  (inova#3 was a Docker-socket crash on a different env, 2026-04-26).
  The fleet has no cross-environment health summary, only point-in-time
  checks inside individual routines.

## Proposed change

**Type:** new feature — fleet-level monitoring
**Name / identifier:** `deploymentDriftReport`

Add a lightweight daily job (could be a new fleet routine, or a step
appended to Routine 3) that queries the `/mcp/info` endpoint on every
known IBMiMCP deployment (local-dev, homelab, cloud) and compares
`features.tools` counts. When any environment diverges by more than N
tools from the highest count, write a warning to
`fleet-workspace/summary.md` and file a `severity/P1` issue in the
iNova repo.

This does not require a new IBMiMCP tool — it's orchestration logic
that runs in the fleet. Implementation is ~40 lines of Python added to
a fleet script or a new `agents/monitor.md` entry.

**Minimum viable scope:**
- Read deployment URLs from `contexts/inova.md` (new `deployment_urls`
  field)
- Curl each `/mcp/info`; parse `features.tools`
- Alert if max − min > 10 (threshold configurable)

## Why this project is the right place for this

iNova owns the deployment topology and the CI/CD gates; the fleet
already has the right GitHub access to file issues and push summaries.

## Implementation notes

```python
import httpx, json
urls = ["https://inovaide.com/mcp/info", "http://192.168.68.89:3051/info"]
counts = {u: httpx.get(u, timeout=5).json()["features"]["tools"] for u in urls}
if max(counts.values()) - min(counts.values()) > 10:
    # file P1 issue via GitHub API
```

The `/mcp/info` endpoint is already implemented and returns
`{name, version, mode, features: {tools: N}}`.

## Effort estimate

**Low** — ~40 lines of Python in a new script +
`contexts/inova.md` update to add `deployment_urls`.

## Risk / caveats

- Cloud endpoint requires Twingate or public exposure — verify
  `https://inovaide.com/mcp/info` is reachable before relying on it.
- The alert threshold (10 tools) is a starting point; tune after
  one week of baseline data.
