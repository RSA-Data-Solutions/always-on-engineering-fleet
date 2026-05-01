# Research Summary — 2026-05-01

Project: IBMiMCP
Searched: r/IBMi (Reddit), code400.com, GitHub (IBM/ibmi-mcp-server, codefori/vscode-ibmi, rsa-data-solutions/inova, rsa-data-solutions/ibmimcp), X/Mastodon

Top finding: Mapepire connection slowness (bobcozzi, codefori/vscode-ibmi #3170, Apr 24) and CCSID/encoding failures for non-ASCII source member names (DrIce99, #3169, Apr 24) represent two active IBM i modernisation friction points that IBMiMCP has no coverage for.

Proposals submitted: 2 (see index.md).

Highest priority: diagnoseMapepiReconnect — IBMiMCP has no visibility into Mapepire pool health, making slow-tool diagnosis impossible; directly relevant to the cloud IBMiMCP tool-count issue (inova #6) where startup pool failure is a leading hypothesis.

Note: Reddit and X/Mastodon search returned no indexable IBM i posts from the last 24 hours specifically. Signal above is from the last 7 days across GitHub issue trackers. No manufactured concerns — quiet day on social; GitHub issues remain the strongest signal channel for this community.
