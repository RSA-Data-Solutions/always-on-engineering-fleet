# Research Summary — 2026-04-27

Project: iNova / IBMiMCP
Searched: iNova GitHub issue tracker, IBMiMCP GitHub issue tracker,
reddit.com/r/IBMi, code400.com, ibm.github.io/ibmi-oss-resources,
blog.richardschoen.net, IBM i community web (April 2026 results).

Top finding: Two P0 deployment failures filed yesterday (2026-04-26)
in the iNova tracker reveal a systemic gap — the fleet has no
cross-environment health baseline, so stale deployments go undetected
for weeks until a gate check fires.

Proposals submitted: 3 (see index.md).

Highest priority: `ibmimcp-deployment-drift-monitor` — the cloud
IBMiMCP container ran with 47/164 tools for 20+ days undetected;
a lightweight cross-env tool-count comparison would catch this
within one daily cycle.

Note on community signal depth: r/IBMi, code400.com, and #IBMiOSS did
not surface indexable posts from the last 24 hours via web search
(community forums update faster than crawlers). The PASE package
discoverability signal (proposal 3) is from a dated April 2026 blog
post; it is a real recurring pain but not strictly "last 24h".
Quiet-day rule does not apply — two P0 issues from the tracker are
clear signal.
