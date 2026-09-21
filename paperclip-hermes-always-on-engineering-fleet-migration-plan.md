# Paperclip + Hermes Migration Plan

## Purpose

Migrate the existing [`RSA-Data-Solutions/always-on-engineering-fleet`](https://github.com/RSA-Data-Solutions/always-on-engineering-fleet) design to a self-hosted Paperclip + Hermes operating model on a machine running llama.cpp with an Intel Arc B60 24 GB GPU and 32 GB host RAM.

This document is written as an execution and verification handoff for Claude. It is intentionally conservative: preserve GitHub Actions as the deterministic CI/policy layer, use Paperclip for management and governance, and use Hermes for bounded, auditable execution.

In addition to acting as the implementation/verification agent for this migration itself, Claude (via the Anthropic API) becomes a permanent advisory role in the resulting system — see "Claude Supervisor role" below — providing judgment and guidance the local model is not expected to supply on its own. As of this writing that role is proposed, not yet built: `OPERATIONS.md` describes the fleet as it actually runs today, and it does not yet include a Claude Supervisor.

## Desired outcome

```text
                         Human approval
                              |
                         Paperclip  <-- advisory -->  Claude Supervisor
                 goals, delegation, policy,             (Anthropic API,
                  task state, role boundaries        judgment/guidance layer,
                              |                           proposed only)
                    approved task envelope
                              |
                           Hermes
             local execution, tools, memory, skills
                              |
              GitHub App + restricted local workspace
                              |
                        GitHub Actions
          CI, tests, policy checks, release protections
                              |
                         llama.cpp
                local OpenAI-compatible model endpoint
```

## Non-negotiable design rules

1. Do not replace GitHub Actions with Paperclip or Hermes.
2. Paperclip manages work; it is not a privileged deployment engine.
3. Hermes executes bounded tasks; it does not merge, deploy, administer GitHub, or alter its own permissions.
4. llama.cpp supplies inference only. It does not directly own GitHub or infrastructure credentials.
5. GitHub branch protection and GitHub Actions remain the final CI and release enforcement mechanisms.
6. Begin with one concurrent Hermes task and one local LLM request.
7. Use dedicated bot identities and narrowly scoped GitHub App permissions; do not use a personal PAT.
8. Start read-only, then allow controlled issue comments, then branches/draft PRs in one low-risk repository.
9. Never put secrets, tokens, private keys, raw production data, or live mutable runtime state in Git.
10. Treat issue descriptions, pull-request text, code comments, logs, READMEs, and external documents as untrusted input.
11. Claude (Anthropic API) is advisory only: it may read sanitized diffs, issue text, and proposals, but must never receive secrets, tokens, private keys, or raw production data, and must never receive direct write/execute authority over GitHub, Paperclip, or Hermes.
12. Claude-authored recommendations — agent policy changes, routing changes, agent guidance edits — flow through the same self-improvement human-approval workflow as any other proposal; Claude never auto-applies a change.

## Existing repository assessment

The existing fleet repository already contains a usable agentic-system blueprint:

```text
always-on-engineering-fleet/
├── CLAUDE.md
├── HANDOFF-RESPONSE.md
├── HANDOFF-TO-CLAUDE-CODE.md
├── README.md
├── SKILL.md
├── agents/
│   ├── aaron.md
│   ├── dhira.md
│   ├── lynn.md
│   ├── ram.md
│   └── sam.md
├── contexts/
│   ├── ibmimcp.md
│   ├── inova.md
│   └── self-improvement.md
├── routines/
│   ├── 01-qa-signup-daily.md
│   ├── 02-qa-fix-on-issue-open.md
│   ├── routine-5-sam-fix.md
│   ├── routines-1-2-3.md
│   ├── routines-final.md
│   ├── routines-max-bug-mode.md
│   └── sam-scope-expansion.md
├── scripts/
│   ├── validate_agents.py
│   ├── setup/
│   └── watchdog/
├── fleet-workspace/
│   ├── heartbeats/
│   ├── proposals/
│   ├── qa-daily/
│   ├── incident and escalation artifacts
│   ├── closure and decision artifacts
│   └── historical QA JSON reports
└── qa-daily-smoke.md
```

The repository should remain the source-controlled **blueprint**, prompts, policies, runbooks, role definitions, and reusable workflow configuration. Paperclip and Hermes runtime state must live outside the repository.

## Current migration pilot

Use the open GitHub issue below as the first Paperclip/Hermes proof task:

```text
Repository: RSA-Data-Solutions/always-on-engineering-fleet
Issue: #11
Title: ALERT: qa-smoke-daily blocked — iNova repo unreachable for 33 consecutive days
Labels: env-problem, blocked, qa
```

This is a safe first task because it is an investigation and evidence-generation activity. It must initially be read-only: no source changes, no configuration changes, no PR creation, no deployment, and no credential rotation.

## Component responsibilities

| Component | Responsibility | Explicitly not responsible for |
|---|---|---|
| Paperclip | Goals, tasks, scheduling, role delegation, approval gates, budget/concurrency tracking, operational dashboard | Merging, deployment, unbounded shell access, GitHub administration |
| Hermes | Task execution, GitHub/API inspection, CI diagnosis, testing, report generation, later bounded draft-PR generation | Merging, release/tag creation, secret access, infrastructure administration |
| Claude Supervisor (proposed) | Plan/routing review, PR/patch second opinion, self-improvement proposal review, agent-guidance quality audit | Merging, deployment, direct edits to agent/policy/repository files, credential access, high-volume primary execution |
| llama.cpp | Local model inference through an OpenAI-compatible API | GitHub writes, task governance, credential management |
| GitHub Actions | Builds, tests, deterministic policy checks, artifacts, required checks, release gates | Long-lived agent memory or business-priority decisions |
| GitHub Issues/PRs | Canonical code-work discussion, review, and code change records | Live agent queue/heartbeat state |
| PostgreSQL | Paperclip durable task/management state | Repository source/configuration storage |
| Hermes audit storage | Sanitized task traces, evidence, optional curated memory | Secrets, raw credentials, persistent arbitrary workspaces |
| Human owner | Scope approval, privilege approval, PR review, merge, release, policy change | Routine low-risk read-only diagnosis |

## Hardware plan

Host resources:

```text
GPU: Intel Arc B60, 24 GB VRAM
RAM: 32 GB system memory
Runtime: llama.cpp
```

### Initial resource policy

Do not operate five concurrent local coding agents. Run a single active Hermes task and serialize work through Paperclip.

```yaml
fleet_limits:
  paperclip_planners: 1
  hermes_active_tasks: 1
  hermes_parallel_tool_calls: 2   # sequential/pipelined tool calls within one model turn — NOT concurrent generations
  local_llm_concurrent_requests: 1
  coding_task_timeout_minutes: 45
  test_task_timeout_minutes: 30
  queued_tasks_per_repository: 1
```

`hermes_parallel_tool_calls` must never be read as "set `--parallel 2` on llama-server." llama.cpp's server divides the total `-c` context budget across `--parallel` slots, so raising `--parallel` would silently cut the configured 98K context per request. Keep `--parallel 1` always — it also matches the "one active Hermes task" rule.

### Initial model strategy

Both Paperclip and Hermes call the **same** llama.cpp endpoint and the **same** loaded model. A separate small planner model alongside a large coder model was considered and rejected for this hardware: with one GPU and a single concurrent-request limit already in place, a second model either double-books VRAM that the large context needs, or requires hot-swapping models per request (10–60s load stalls that erase any latency benefit of a "fast" planner). Paperclip's planning calls are naturally short-context, so they run cheaply on the shared model without a dedicated tier.

This host already has a deployed model, confirmed live at time of writing: **Qwen3-Coder-30B-A3B-Instruct**, unsloth `UD-Q4_K_XL` GGUF quant, served via `llama-qwen.service`. This is a good fit for the shared-model strategy:

```text
Model:            Qwen3-Coder-30B-A3B-Instruct (unsloth UD-Q4_K_XL, ftype "Q4_K - Medium")
Architecture:     qwen3moe (Mixture-of-Experts)
Total params:     30.53B  (128 experts, 8 active per token, ~3B active — the "A3B")
Weight file size: 17,659,361,280 bytes (~16.45 GiB)
Layers:           48
Attention heads:  32 (query), 4 (key/value — GQA 8:1)
Head dim:         128
Native n_ctx_train: 262,144  (98K deployed is well inside the model's trained range)
```

| Work type | Model / endpoint | Context policy |
|---|---|---|
| Paperclip planning/routing | Shared llama.cpp model (Qwen3-Coder-30B-A3B) | Short prompts in practice; no special handling needed |
| Hermes issue/CI triage | Shared llama.cpp model | Normal working budget (~16K–32K); one request at a time |
| Hermes code changes | Shared llama.cpp model | Normal working budget (~16K–32K) by default |
| Large/refactor tasks | Shared llama.cpp model | Explicitly allowed to grow toward the full 98K ceiling for this one queued task only |
| RAG/embeddings | Small dedicated embedding model or off-hours scheduled task | Do not compete with active coding inference |

98K is the available ceiling on this host, not the default working size, for two reasons:

1. **VRAM fit is real but tight** — see "llama.cpp capacity for 98K context" below.
2. **Quality degrades before the context limit does.** Even MoE coding models typically show retrieval/reasoning degradation well before 90K+ tokens, independent of whether the tokens physically fit. Keeping normal tasks in a smaller working budget is a deliberate quality/latency choice, not a hardware limitation being worked around.

### llama.cpp capacity for 98K context — measured against the actual deployed model

KV cache size per token is:

```text
bytes/token = 2 (K+V) x n_layers x n_kv_heads x head_dim x bytes_per_element
```

For the real deployed model (48 layers, 4 KV heads — not 32; GQA collapses attention heads 8:1 — head_dim 128):

```text
2 x 48 x 4 x 128 = 49,152 elements/token
f16  KV (2.0 B/elem): ~96 KB/token  -> 98,304 tokens ~= 9.0 GB
q8_0 KV (~1.0 B/elem): ~48 KB/token -> 98,304 tokens ~= 4.6 GB   <- this host's actual configured setting
q4_0 KV (~0.5 B/elem): ~24 KB/token -> 98,304 tokens ~= 2.3 GB
```

Total VRAM budget at the deployed settings (`-ctk q8_0 -ctv q8_0 -fa on`, `-c 98304`, `--parallel 1`):

```text
Model weights (Q4_K_XL):        ~17.7 GB
KV cache (q8_0, 98,304 ctx):     ~4.6 GB
Compute/ubatch buffers (-ub 1024, graph overhead): roughly 1-2 GB
---------------------------------------------------------------
Estimated total:                ~23.5-24.3 GB   on a 24 GB card
```

**This is why the MoE architecture matters:** KV cache cost is driven entirely by attention dimensions (layers x KV heads x head_dim), not by total parameter count. A 30B-parameter MoE model with only 4 KV heads has a smaller KV footprint than a much smaller *dense* model with more KV heads — the earlier generic "14B dense model" estimate in this document materially overstated the KV cost for this specific model. That is what makes a 98K ceiling viable here at all despite the model's large nominal size.

The estimate above lands right at the 24 GB ceiling with little headroom — treat it as tight, not comfortable. Practical implications:

- There is essentially no VRAM margin for a second concurrent load of this model, a second model, or a larger `--parallel` value at this context size.
- If host measurement shows instability (OOM, driver eviction, thrashing) at sustained 90K+ token requests, drop to `q4_0` KV cache (frees ~2.3 GB) or reduce the ctx ceiling (e.g. 64K) before touching quantization of the weights themselves.
- Re-run this calculation if the model file changes — do not assume it transfers.

**Note on the two `llama-server` processes visible in `ps aux` (checked 2026-09-12):** at first glance this looked like two independent instances double-loading the same model — `PID 2303376` (`llama-qwen.service`, `0.0.0.0:8080`, the `--models-dir`/`--models-max 1` router, API-key protected) and `PID 157316` (`127.0.0.1:46567`, a direct `-m` load, no API key). Checking the process tree showed `157316`'s parent is `2303376`, and `tools/server/server-models.cpp` in this llama.cpp checkout is the router's model-worker implementation — so `:46567` is not a second, independent instance. It is the router's own child worker process that actually holds the model and serves inference, reached only by the router proxying to it internally. There is one model resident in VRAM, matching the capacity estimate above, not two. Do not stop the `:46567` process directly — it is the running model backing the production `:8080` endpoint, and killing it just forces the router to reload (or errors requests) rather than freeing anything meaningful.

### Memory pressure rules

1. Configure llama.cpp for the full 98K context ceiling using flash attention (`-fa`) and a quantized KV cache (`--cache-type-k q8_0 --cache-type-v q8_0`, or `q4_0` if VRAM is still tight) so the ceiling actually fits in 24 GB alongside model weights — see the capacity math above.
2. Use one active generation/request (`--parallel 1`).
3. Measure host RAM, GPU VRAM, swap, latency, and OOM events under a real request near the 90K+ token range, not just at idle.
4. If unstable, drop the configured context ceiling (e.g. to 64K or 32K) before changing model quantization or adding concurrency.
5. Do not allow test/build containers to run concurrently with a large local inference job unless measurement shows headroom.
6. Structure Hermes task conversations as append-only — never rewrite or reorder earlier turns. llama.cpp's server caches the processed prefix per slot; with `--parallel 1` there is exactly one slot, so an append-only conversation reuses that cache and each new turn only pays prefill cost for new tokens. A framework that reconstructs the prompt from scratch every turn would reprocess up to 90K+ tokens of prefill per tool call — tens of seconds of dead time on this hardware, risking the 45-minute task timeout on any nontrivial task.

## Host preparation

### Recommended service separation

Use separate service accounts and separate persistent directories:

```bash
sudo useradd --system --create-home --home-dir /srv/paperclip paperclip
sudo useradd --system --create-home --home-dir /srv/hermes hermes
sudo useradd --system --create-home --home-dir /srv/llama llama
sudo useradd --system --create-home --home-dir /srv/claude-supervisor claude-supervisor

sudo install -d -o paperclip -g paperclip /srv/paperclip/data
sudo install -d -o paperclip -g paperclip /srv/paperclip/postgres
sudo install -d -o hermes -g hermes /srv/hermes/config
sudo install -d -o hermes -g hermes /srv/hermes/workspaces
sudo install -d -o hermes -g hermes /srv/hermes/audit
sudo install -d -o llama -g llama /srv/llama/models
sudo install -d -o llama -g llama /srv/llama/cache
sudo install -d -o claude-supervisor -g claude-supervisor /srv/claude-supervisor/config
```

### Isolation requirements

- Run Paperclip, PostgreSQL, Hermes, and llama.cpp as separate services or containers.
- Do not give Hermes access to `/var/run/docker.sock`.
- Do not give Hermes the `sudo` command, root access, SSH keys, cloud credentials, Proxmox credentials, router credentials, home automation credentials, Tailscale/WireGuard keys, or personal GitHub credentials.
- Restrict Hermes checkout/workspace activity to `/srv/hermes/workspaces`.
- Use ephemeral per-task workspaces and delete completed workspaces after a short retention period.
- Keep Paperclip and Hermes on an internal network. Prefer Tailscale/WireGuard access or VPN-only access for the Paperclip UI.
- Use TLS and strong authentication if Paperclip is accessible remotely.
- Run Claude Supervisor as its own service identity (`claude-supervisor`) with egress restricted to `api.anthropic.com`; it must not hold the GitHub App private key, any Paperclip `task_bridge` key, the Paperclip board token, or `LLAMA_API_KEY`.

## llama.cpp deployment

This host already runs llama.cpp as a systemd service — do not stand up a competing deployment. The actual unit in place (`/etc/systemd/system/llama-qwen.service`, backend: Vulkan build at `build-vulkan/bin/llama-server`, confirming Vulkan — not SYCL/oneAPI — is the backend in production use on this Arc B60):

```ini
# /etc/systemd/system/llama-qwen.service
[Unit]
Description=llama.cpp Vulkan server — Qwen3 Coder on Intel Arc B60
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=sashi
Group=sashi
SupplementaryGroups=render video
WorkingDirectory=/home/sashi/Documents/ai/llama.cpp
EnvironmentFile=/etc/default/llama-qwen

Environment=HOME=/home/sashi
Environment=GGML_VK_VISIBLE_DEVICES=0
Environment=VK_LOADER_DEBUG=error

ExecStart=/home/sashi/Documents/ai/llama.cpp/build-vulkan/bin/llama-server \
  --models-dir /home/sashi/Documents/ai/models/llamacpp \
  --models-max 1 \
  -ngl 999 \
  --parallel 1 \
  -c 98304 \
  -ctk q8_0 \
  -ctv q8_0 \
  -ub 1024 \
  --cache-reuse 256 \
  -fa on \
  --host 0.0.0.0 \
  --port 8080

Restart=on-failure
RestartSec=10
TimeoutStopSec=90
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

The live unit currently has the API key inlined directly as a `--api-key` argument in `ExecStart`, which is why it showed up in plain text in `ps aux` output (readable by any local user via `/proc/PID/cmdline`, and easy to leak into logs/screenshots). Referencing it as `--api-key ${LLAMA_API_KEY}` would **not** fix this — systemd resolves `${VAR}` substitutions in `ExecStart=` before calling `execve()`, so the resolved plaintext key still ends up in the process's argv and is still visible in `ps aux`. The actual fix, applied above: drop `--api-key` from `ExecStart` entirely and set `LLAMA_API_KEY` via `EnvironmentFile=` instead — `llama-server`'s argument parser (`common/arg.cpp`, the `--api-key` option is registered with `set_env("LLAMA_API_KEY")`) reads it directly from the process environment when the flag is absent, so the key never appears in argv/cmdline at all. Keep the environment file at mode 600, owned by the service's user (`sashi`), and do not commit it or its value anywhere, per the repo's own "never put secrets in Git" rule.

This deployment already implements the recommendations from the capacity analysis above: `-fa on` plus `-ctk/-ctv q8_0` quantized KV cache, `--parallel 1`, and `-c 98304`. `--models-dir`/`--models-max 1` is llama.cpp's built-in single-model router — it can serve multiple GGUFs from that directory (there is also a `dolphin-llama31-8b-q4-k-m.gguf` symlinked alongside the Qwen model) but never loads more than one at a time, which is the correct behavior for a 24 GB card that's already near saturation with one model resident.

Notes for Claude:

- Flash attention and quantized KV cache are confirmed working on this Vulkan build (the live server reports `n_ctx: 98304` via `/props` and is healthy) — the earlier generic caveat about verifying backend support is resolved for this host. Still re-verify after any llama.cpp binary upgrade, since Vulkan op coverage has changed across releases.
- The process visible on `127.0.0.1:46567` is the router's own model-worker child (see note above) — expected, not a second instance to clean up. Point Hermes/Paperclip only at `:8080`; never at the internal worker port directly, since the router may recycle or renumber that worker process.
- Bind the production endpoint per the existing unit: `0.0.0.0:8080` protected by the API key, reachable on the LAN (`192.168.68.0/24`). Any access beyond the LAN must go through a separately, manually configured tunnel (e.g. Cloudflare Tunnel) sitting in front of the API key, not instead of it — never rely on the API key alone once the endpoint is reachable from outside the LAN.
- Point Hermes's `base_url` at `http://127.0.0.1:8080/v1` (or the LAN IP) and supply the API key as a bearer token from Hermes's own secret store, not hardcoded in `hermes.yaml`.

Validation:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now llama-qwen
curl --fail -H "Authorization: Bearer $LLAMA_API_KEY" http://127.0.0.1:8080/health
curl --fail -H "Authorization: Bearer $LLAMA_API_KEY" http://127.0.0.1:8080/v1/models
```

## Paperclip deployment

### Runtime layout

```text
Reverse proxy or private VPN access
              |
           Paperclip
              |
         PostgreSQL
              |
    Persistent backup target
```

### Deployment requirements

1. Pin Paperclip to a specific release/image digest or source commit.
2. Use a dedicated PostgreSQL database and durable volume.
3. Store the database password in an environment file or secret store readable only by Paperclip/PostgreSQL service identities.
4. Bind Paperclip to loopback or private network first.
5. Implement daily encrypted backups and test restoration.
6. Record deployed version, image digest, configuration checksum, and backup validation status in operational documentation.
7. Do not expose a privileged Paperclip API publicly for direct webhook traffic.

Illustrative Compose skeleton:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: paperclip-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: paperclip
      POSTGRES_USER: paperclip
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - /srv/paperclip/postgres:/var/lib/postgresql/data
    networks:
      - paperclip-internal

  paperclip:
    image: <PINNED_PAPERCLIP_IMAGE>
    container_name: paperclip
    restart: unless-stopped
    depends_on:
      - postgres
    environment:
      DATABASE_URL: postgresql://paperclip:${POSTGRES_PASSWORD}@postgres:5432/paperclip
      # Add only variables documented by the selected Paperclip release.
    volumes:
      - /srv/paperclip/data:/app/data
    ports:
      - "127.0.0.1:3100:3100"
    networks:
      - paperclip-internal

networks:
  paperclip-internal:
    driver: bridge
```

Do not proceed until Paperclip is reachable locally, persists a restart, and its PostgreSQL backup can be restored in a test location.

## Hermes deployment

Run Hermes as a separate worker. Hermes should receive a signed/validated Paperclip task envelope, never a broad free-form instruction with unrestricted tools.

Illustrative intended configuration model:

```yaml
# /srv/hermes/config/hermes.yaml
runtime:
  mode: worker
  task_timeout_minutes: 45
  max_active_tasks: 1
  workspace_root: /srv/hermes/workspaces
  cleanup_workspaces: true
  retain_completed_task_hours: 24

models:
  default:
    provider: openai_compatible
    base_url: http://127.0.0.1:8080/v1        # the existing llama-qwen.service router
    model: qwen3-coder-30b-a3b-q4-k-xl          # matches the alias reported by /v1/models
    api_key_env: LLAMA_API_KEY                  # read from Hermes's own secret store, never hardcoded here
    max_concurrent_requests: 1
    context_budget_tokens: 24000       # normal working budget for triage/coding tasks
    context_ceiling_tokens: 98304      # hard ceiling; matches this host's deployed -c 98304 — only large/refactor task class may approach this

github:
  auth_mode: github_app
  allowed_organizations:
    - RSA-Data-Solutions
  allowed_repositories:
    - RSA-Data-Solutions/always-on-engineering-fleet
  default_access: read_only

paperclip:
  endpoint: http://127.0.0.1:3100
  worker_identity: hermes-engineering-worker
  require_signed_task_envelope: true

security:
  allow_network_egress:
    - api.github.com
    - github.com
    - 127.0.0.1
  deny_shell_commands:
    - sudo
    - su
    - ssh
    - scp
    - rsync
    - kubectl
    - terraform
    - ansible-playbook
    - docker
    - podman
  prohibit_paths:
    - /etc
    - /home
    - /root
    - /var/run/docker.sock
```

This is a policy-model example. Claude must validate the actual current Hermes configuration and integration syntax against the selected Hermes release before implementation.

### Hermes mandatory controls

- One active task only.
- Workspace is per task and ephemeral.
- Read-only GitHub access during Phase 1.
- Network egress allowlisted where feasible.
- Tool execution permitlist, not broad shell access.
- Full structured audit of task ID, prompt/version, repository, SHA, tool call, timestamp, exit status, and created artifacts.
- No direct access to Paperclip database.
- No ability to alter agent roles, policy, tool allowlists, model routing, or its own service definition.

## GitHub App setup

Create a dedicated GitHub App for the Paperclip/Hermes integration. Install it only on the pilot repository first:

```text
RSA-Data-Solutions/always-on-engineering-fleet
```

### Initial GitHub App permissions

| Permission | Initial level | Purpose |
|---|---|---|
| Metadata | Read | Repository identity and basic context |
| Contents | Read | Read source, contexts, prompts, runbooks |
| Issues | Read/write | Triage/status comments only |
| Pull requests | Read | Read PR state and diff metadata |
| Actions | Read | CI/workflow inspection where available |
| Checks | Read | CI result interpretation |
| Commit statuses | Read | Build health context |
| Contents write | None | No branches/code modifications in Phase 1 |
| Pull requests write | None | No PR creation in Phase 1 |
| Administration | None | Never grant for standard fleet work |

### Later draft-PR identity

After a successful read-only pilot, create a separate narrow writer identity or a separate GitHub App installation with only the minimum needed permission for one explicitly approved repository:

- Contents: write
- Pull requests: write
- Issues: read/write
- Metadata: read
- Actions/Checks: read

This writer must still be unable to merge, alter repository settings, modify protection rules, access secrets, or administer organization membership.

## Agent role migration

Preserve the current `agents/*.md` material as role descriptions, but convert each role to explicit Paperclip/Hermes configuration with permissions, model profile, scope, prohibited actions, inputs, outputs, and escalation rules.

### Initial role model

| Role | Runtime | Intended function | Initial authority |
|---|---|---|---|
| Engineering Manager | Paperclip-managed planner | Break goals into bounded tasks, route work, flag blockers | Paperclip tasks and GitHub issue metadata; no shell, no source writes |
| Hermes Triage | Hermes | Diagnose CI failures, issue conditions, QA failures, environment symptoms | Read repository/Actions; write issue comments only |
| QA Agent | Hermes or separate profile | Execute documented smoke tests, assess evidence, prepare reports | Workspace-only commands; no source writes |
| Reviewer/Security Agent | Hermes read-only profile | Check diffs/policy violations, assess prompt-injection and secret risk | Read-only GitHub and analysis tools |
| Hermes Implementer | Hermes | Create minimal fixes for approved low-risk work | Disabled until Phase 3; then branch + draft PR only |
| Human Owner | User | Approve scope/access, review PRs, merge, release, change policies | Final authority |

### Agent manifest example

```yaml
id: qa-triage
display_name: QA Triage Agent
runtime: hermes
model_profile: local-fast
max_active_tasks: 1

scope:
  repositories:
    - RSA-Data-Solutions/always-on-engineering-fleet
  allowed_tasks:
    - inspect_ci_failure
    - run_documented_smoke_test
    - summarize_issue
    - create_evidence_report

permissions:
  github:
    contents: read
    issues: write
    pull_requests: read
    actions: read
  filesystem:
    workspace_only: true
  shell:
    allowed:
      - git
      - gh
      - python
      - pytest
      - node
      - npm
    denied:
      - sudo
      - ssh
      - docker
      - podman

requires_human_approval:
  - create_branch
  - create_pull_request
  - modify_workflow
  - modify_agent_policy
  - modify_infrastructure
  - merge_pull_request
  - deploy
```

### Mapping existing named agents

Claude should inspect the current contents of `agents/aaron.md`, `agents/dhira.md`, `agents/lynn.md`, `agents/ram.md`, and `agents/sam.md` and map actual responsibilities into the above role model. Do not infer authority from agent name alone.

Suggested initial mapping to validate:

```text
Ram: Paperclip engineering lead / dispatcher; no shell and no source writes.
Sam: Hermes implementation profile; disabled until controlled draft-PR phase.
Aaron/Dhira/Lynn: Specialized QA, research, review, or operations profiles as supported by their existing definitions.
```

## Claude Supervisor role

The intent for this migration is for Claude (Anthropic API) to act as the fleet's
judgment/guidance layer — reviewing plans, PR/patch-worthy output, and the agents' own
operating instructions for quality — while the local Qwen3-Coder model handles high-volume
bounded execution. This is not yet built. `OPERATIONS.md` describes the fleet exactly as it
runs today (Ram/Aaron/Dhira/Lynn/Sam as real Paperclip agents, `hermes_local`/`hermes_gateway`
execution paths, Slack/Telegram delegation) and it has no Claude role in it. What follows is a
proposal to fit into that real system, not a description of what already exists.

### Authority

Claude Supervisor is advisory only. It has:

- No shell access, no GitHub write/merge authority, no ability to call `paperclipai approval
  approve`/`reject`, and no ability to alter agent identity, permissions, system prompts, tool
  policy, model routing, or service deployment — the same restriction the self-improvement
  policy already places on Hermes. `OPERATIONS.md` documents that even an agent-level Paperclip
  key gets `403: Board access required` on approval decisions; Claude gets no more authority
  than that, and in practice should get less.
- Read access limited to sanitized text: task/issue descriptions, diffs, PR text, proposal
  documents, and agent role/guidance text — never secrets, tokens, private keys, or raw
  production data (extends rule 9).
- Output limited to structured recommendations, risk annotations, and improvement proposals
  that flow into the existing human-approval and self-improvement pipelines. Claude never
  auto-applies a change to `agents/*.md`, a live Paperclip agent's instructions bundle, or
  repository content.

### Integration points

1. **Plan/routing review** — before Ram delegates an ambiguous or higher-risk request to
   Aaron/Dhira/Lynn/Sam via the `paperclip-task-bridge` skill, Claude may review the proposed
   task description and routing for soundness. Advisory; Ram/Paperclip still owns the actual
   `create-task` call.
2. **PR/patch second opinion** — inserted between an agent's work and the disposition it
   self-reports (`done`/`blocked`/`in_review`) reaching a human in Slack. `OPERATIONS.md`
   names a specific, already-observed failure mode this addresses directly: the local model
   "fabricating status (completed and merged when the real status was blocked)." Claude reviews
   the actual diff/patch and issue history — not Ram's narrated summary — and attaches a
   confidence/risk annotation. It can raise (never lower) a risk label if it disagrees with the
   agent's self-assessment, but cannot block or approve on its own.
3. **Self-improvement proposal review** — Claude fills the "Reviewer agent checks proposal and
   test plan" step already defined in `contexts/self-improvement.md`'s required workflow. This
   is the highest-value use of Claude given the low volume and high stakes of self-improvement
   changes.
4. **Agent-guidance quality audit** — periodically (see "Weekly" operations), Claude reviews
   `agents/*.md` against observed failure patterns (recurring escalations, duplicate-task
   creation, the other named failure modes in `OPERATIONS.md`'s "Known limitations") and
   produces an improvement proposal. This still goes through the standard self-improvement
   workflow and human approval — it does not call `paperclipai agent instructions-file:put`
   itself, per the repo's existing rule against ad-hoc agent-file edits.

### Data boundary and cost control

- Claude must never receive any of the credentials `OPERATIONS.md` documents as live today:
  `LLAMA_API_KEY`, the Paperclip board token, Ram's `task_bridge` or standard API keys, any
  report's own `task_bridge` key, `API_SERVER_KEY`, or the Slack tokens. Sanitize before
  sending anything to Claude.
- Run Claude calls from a narrow adapter identity (`claude-supervisor`), never from inside
  `hermes_gateway` (which already runs with `hooks_auto_accept: true` and full tool access) or
  a `hermes_local` run holding a live `task_bridge` key.
- Add `api.anthropic.com` egress for that adapter only — Hermes's own network policy should
  not be the thing deciding what leaves the network to a third-party API.
- Store the Anthropic API key the same way other secrets are handled here: outside Git, mode
  600, owned by the adapter's own service identity.
- Gate invocation to the triggers above rather than calling Claude on every ~30s Paperclip
  heartbeat — this keeps latency and API cost proportional to the value of the judgment call,
  not the volume of local-model activity.

### Where this would actually plug in

Per `OPERATIONS.md`'s own "Adding a new agent" procedure, the natural shape is a new Paperclip
agent — reporting to Ram or a peer of Ram — whose `adapterConfig` targets the Anthropic API
instead of the shared `llama-qwen.service` endpoint, with no `task_bridge` key capable of
`create-task`/`update-status` on anyone else's work, only enough scope to read issues/diffs and
post its own review as a comment or as the payload of a `paperclipai approval create` request.
Because this role is read-only/advisory by construction, it does not need to wait for a
draft-PR-writing phase to be enabled — it can be introduced alongside the existing read-only
agents, and its self-improvement-review function should be enabled as soon as the
self-improvement workflow itself is exercised.

## Context and skill migration

### Preserve in version control

```text
agents/*.md
contexts/*.md
routines/*.md
SKILL.md
CLAUDE.md
validation scripts
policy/runbook templates
architecture documentation
reusable GitHub workflow definitions
closed historical incident summaries
```

### Move out of Git

```text
live heartbeats
active task locks
worker PIDs and status
raw LLM transcripts
runtime credentials
GitHub App private keys
webhook secrets
temporary checkouts
per-run logs
per-run QA JSON
queue state
model cache
```

### Self-improvement policy

The existing self-improvement context may inform skill proposals but must not authorize autonomous modification of agent identity, permissions, system prompts, tool policy, model routing, Paperclip roles, or service deployment.

Required self-improvement workflow:

```text
Observation or recurring failure
  -> Hermes drafts improvement proposal
  -> Reviewer agent checks proposal and test plan
  -> Human approves a bounded policy/skill change
  -> Git branch + pull request
  -> GitHub Actions validate configuration
  -> Human merges
  -> Deploy a pinned tested revision
```

## Routine migration

Convert existing markdown routines into explicit state machines with trigger, eligibility criteria, authority, inputs, outputs, success criteria, timeout, and escalation.

| Existing routine class | Paperclip responsibility | Hermes responsibility | GitHub Actions responsibility |
|---|---|---|---|
| Daily QA smoke | Schedule task and track state | Run documented smoke test; collect evidence | Trigger/schedule, artifacts, status reporting |
| Issue-open response | Create triage task | Analyze issue read-only and produce diagnosis | Dispatch only after approved labels |
| Bug fix | Create bounded implementation task | Patch/test/open draft PR only after approval | Run CI/policy checks |
| Scope expansion | Flag as review required | Impact analysis only | None |
| Max-bug mode | Incident coordination | Triage/summarize; no broad autonomous edits | Retain logs and deterministic checks |
| Self-improvement | Review proposal task | Recommend changes and tests | Validate metadata/configuration |

### Required task state machine

```text
new
  -> triage
  -> needs-human-approval OR blocked OR rejected
  -> approved
  -> executing
  -> verification
  -> human-review
  -> complete OR failed OR escalated
```

No implementation execution is allowed from `new` or `triage` state. Implementation requires an explicit approved state and matching GitHub labels.

## GitHub label policy

Create and use the following labels:

```text
agent:triage
agent:approved
agent:fix-allowed
agent:review-only
agent:human-review
risk:low
risk:medium
risk:high
blocked
env-problem
qa
domain:inova
domain:ibmi
domain:homelab
domain:product
```

### Label semantics

- `agent:triage`: Hermes may inspect and report; no code writes.
- `agent:approved`: human has approved the task scope.
- `agent:fix-allowed`: a code-writing agent may be considered, subject to risk and repository allowlist.
- `agent:review-only`: no branch or source modification.
- `agent:human-review`: task output needs human decision.
- `risk:low`: eligible for tightly bounded draft-PR work after Phase 3.
- `risk:medium` or `risk:high`: investigation/reporting only unless individually approved.

A write-capable implementation dispatch requires all of:

```text
agent:approved
agent:fix-allowed
risk:low
```

## GitHub Actions integration

GitHub Actions stays authoritative for deterministic evaluation. Do not execute arbitrary agent-proposed commands directly in privileged GitHub runners.

### Scheduled QA smoke test

The command implementation must be derived from and validated against the existing `qa-daily-smoke.md` runbook.

```yaml
name: QA Daily Smoke

on:
  schedule:
    - cron: "15 12 * * *"
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Run documented smoke test
        run: |
          mkdir -p artifacts
          ./scripts/run-qa-smoke.sh --output artifacts/qa-report.json

      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: qa-smoke-${{ github.run_id }}
          path: artifacts/
          retention-days: 30

      - name: Notify Hermes on failure
        if: failure()
        env:
          HERMES_WEBHOOK_URL: ${{ secrets.HERMES_WEBHOOK_URL }}
          HERMES_WEBHOOK_TOKEN: ${{ secrets.HERMES_WEBHOOK_TOKEN }}
        run: |
          curl --fail --silent --show-error \
            --request POST "$HERMES_WEBHOOK_URL/events/qa-failure" \
            --header "Authorization: Bearer $HERMES_WEBHOOK_TOKEN" \
            --header "Content-Type: application/json" \
            --data '{
              "repository":"${{ github.repository }}",
              "run_id":"${{ github.run_id }}",
              "sha":"${{ github.sha }}",
              "event_type":"qa_smoke_failure"
            }'
```

Only transmit identifiers to Hermes. Hermes uses its own GitHub App identity to fetch allowed context. Do not transmit GitHub tokens, arbitrary secret values, or raw environment variables.

### Label-gated Paperclip dispatch

```yaml
name: Paperclip Agent Dispatch

on:
  issues:
    types: [labeled]

permissions:
  contents: read
  issues: read

jobs:
  dispatch:
    if: >
      github.event.label.name == 'agent:approved' &&
      contains(toJson(github.event.issue.labels.*.name), 'agent:fix-allowed') &&
      contains(toJson(github.event.issue.labels.*.name), 'risk:low')
    runs-on: ubuntu-latest
    steps:
      - name: Send approved task envelope
        env:
          PAPERCLIP_WEBHOOK_URL: ${{ secrets.PAPERCLIP_WEBHOOK_URL }}
          PAPERCLIP_WEBHOOK_TOKEN: ${{ secrets.PAPERCLIP_WEBHOOK_TOKEN }}
        run: |
          curl --fail --silent --show-error \
            --request POST "$PAPERCLIP_WEBHOOK_URL/inbox/github-task" \
            --header "Authorization: Bearer $PAPERCLIP_WEBHOOK_TOKEN" \
            --header "Content-Type: application/json" \
            --data '{
              "repository":"${{ github.repository }}",
              "issue_number":${{ github.event.issue.number }},
              "issue_node_id":"${{ github.event.issue.node_id }}",
              "event_id":"${{ github.event.delivery }}"
            }'
```

Before implementation, Claude must verify how the selected Paperclip release safely accepts inbound tasks. If a native webhook/API does not exist, create a minimal authenticated adapter service rather than exposing the Paperclip database or using an unauthenticated public endpoint.

### Agent policy check

Create a deterministic PR policy workflow with these requirements:

1. Validate Paperclip/Hermes manifest format and required fields.
2. Run the existing `scripts/validate_agents.py` and extend it for new manifests.
3. Reject accidental commits of runtime state under a designated runtime path.
4. Run secret scanning on changed files.
5. Require a Paperclip task ID and verification evidence in any agent-generated PR.
6. Automatically mark edits to privileged paths as high-risk and require a human reviewer.

## Prohibited autonomous changes

Hermes must not autonomously alter these paths or operations:

```text
.github/workflows/**
.github/actions/**
infra/**
terraform/**
ansible/**
kubernetes/**
k8s/**
helm/**
Dockerfile*
compose*.yml
docker-compose*.yml
*.tf
*.tfvars
.env*
*.pem
*.key
auth/**
identity/**
secrets/**
migrations/**
production deployment configuration
GitHub branch protections
GitHub organization/repository administration
GitHub Actions secrets
releases/tags/deployments
```

Any task involving these items receives `risk:high`, is recommendation-only, and requires explicit human approval before a human performs the change.

## Pilot: iNova QA issue #11

### Paperclip task definition

```text
Goal:
Restore or accurately classify the blocked daily iNova QA smoke workflow.

Repository:
RSA-Data-Solutions/always-on-engineering-fleet

GitHub issue:
#11

Agent:
Hermes Triage

Permissions:
Read-only GitHub, constrained local workspace, only explicitly approved network probes.

No authority:
No branch, PR, code/config edit, secret access, deployment, or credential rotation.

Required output:
- Exact observed failure and timestamp
- DNS/TCP/HTTP classification when safe and authorized
- Whether endpoint, route, credentials, repository access, or test harness is implicated
- Reproduction steps with secrets omitted
- Evidence links or log identifiers
- Recommended owner and next action
- Confidence score and assumptions
```

### Pilot acceptance criteria

- Paperclip creates and tracks the task successfully.
- Hermes receives only a bounded task envelope.
- Hermes queries only approved GitHub/resource scope.
- Local llama.cpp completes the task without OOM or host instability.
- Hermes produces an evidence-based report rather than unsupported claims.
- No unauthorized GitHub source modification occurs.
- The result is posted to Paperclip and optionally as an issue comment only after human review of the content or a predefined low-risk commenting policy.

## Rollout stages

| Phase | Duration | Paperclip | Hermes | GitHub capability | Completion criteria |
|---|---:|---|---|---|---|
| 0. Baseline | 1 day | Deploy database/control plane; create organization | Deploy worker and test llama.cpp endpoint | Existing access only | Services restart cleanly; backup/restore verified |
| 1. Read-only | 1–2 weeks | Goals, queue, approvals, role records; Claude Supervisor available for plan/PR review | CI/QA triage, issue investigation, reports | Read-only plus tightly controlled issue comments | Accurate reports, clean audits, no policy violations |
| 2. Task routing | 1–2 weeks | Dispatch approved investigations | Run bounded task templates | Still read-only source access | Reliable state transitions and useful outputs |
| 3. Draft PR pilot | 2 weeks | Create low-risk implementation task | Branch, minimal patch, test, draft PR | One approved repo, writer identity, no merge | Draft PRs contain evidence and pass checks |
| 4. Independent review | 2–4 weeks | Route QA/reviewer tasks separately | QA/review output on agent PRs | Read/write remains scoped | Findings improve quality without unsafe behavior |
| 5. Expand carefully | After proof | Manage selected additional domains | Scoped operations per repo | Per-repo allowlists only | Evidence of sustained reliability and value |

## Draft-PR policy

Do not enable until the read-only pilot is successful.

A Hermes implementation task may create a branch and draft PR only when:

1. The issue has `agent:approved`, `agent:fix-allowed`, and `risk:low`.
2. The task is in Paperclip `approved` state.
3. The repository is on the explicit writer allowlist.
4. The change does not touch prohibited/high-risk paths.
5. A reproducible failure or precise acceptance criterion exists.
6. The agent runs documented targeted tests.
7. The agent creates a draft PR—not a merge, tag, release, or deployment.

Required draft-PR template:

```markdown
## Agent task
- Paperclip task ID:
- GitHub issue:
- Risk label:
- Requested outcome:

## Diagnosis
- Failure/reproduction:
- Root-cause hypothesis:
- Confidence:

## Change
- Files changed:
- Why this is minimal:
- Explicit non-goals:

## Verification
- Commands run:
- Results:
- CI link:

## Human review required
- [ ] No workflow/security/permission changes
- [ ] No secrets or credential impact
- [ ] No deployment or data migration
- [ ] Required checks pass
```

## Observability and audit

Capture a structured event for every task:

```json
{
  "paperclip_task_id": "...",
  "hermes_task_id": "...",
  "agent_role": "...",
  "repository": "RSA-Data-Solutions/always-on-engineering-fleet",
  "commit_sha": "...",
  "model_profile": "local-coder",
  "model_version": "...",
  "prompt_version": "...",
  "started_at": "...",
  "completed_at": "...",
  "tool_calls": [],
  "commands": [],
  "network_destinations": [],
  "artifacts": [],
  "outcome": "completed|blocked|failed|escalated",
  "human_approval_reference": "..."
}
```

Do not persist raw secrets, private keys, GitHub tokens, or full sensitive prompt content in audit logs.

## Daily operations

### Daily

- Confirm Paperclip, PostgreSQL, Hermes, and llama.cpp service health.
- Review failed scheduled QA checks.
- Review blocked Paperclip tasks.
- Inspect any agent-created issue comments or task reports.
- Check host RAM, VRAM, swap use, disk, and queue depth.

### Weekly

- Review all agent actions and exceptions.
- Review local model quality, latency, hallucination/error rates, and repeated-failure patterns.
- Validate backups and inspect audit-log retention.
- Update repository allowlists only if justified by pilot evidence.
- Review self-improvement proposals as normal code/config changes.

### Monthly

- Test Paperclip PostgreSQL restoration.
- Rotate webhook tokens and GitHub App private keys as appropriate.
- Review all agents’ required permissions and remove unused ones.
- Review exposed network surfaces and TLS/VPN settings.
- Reassess model/context settings against host resource data.

## Claude verification checklist

### Repository analysis

- [ ] Read `README.md`, `CLAUDE.md`, `SKILL.md`, and existing handoff files.
- [ ] Read every `agents/*.md` file and identify exact responsibilities, inputs, outputs, and implied authority.
- [ ] Read every `routines/*.md` file and convert each into a bounded state-machine specification.
- [ ] Read `contexts/*.md`; classify material as task knowledge, policy, sensitive context, or obsolete context.
- [ ] Inspect `scripts/validate_agents.py`, `scripts/setup/`, and `scripts/watchdog/` before changing anything.
- [ ] Inspect `qa-daily-smoke.md` and historical QA artifacts to derive an executable, deterministic smoke-test contract.
- [ ] Preserve historical fleet-workspace incident artifacts, but design live runtime state outside Git.

### Platform validation

- [ ] Confirm OS, kernel, llama.cpp build, Arc GPU backend, and model inference stability.
- [ ] Measure RAM/VRAM/swap under one long local inference request near the 90K+ token range, not just at idle — the capacity math in "llama.cpp deployment" puts the deployed model within ~1 GB of the 24 GB ceiling.
- [ ] Confirm exactly one model is resident in GPU VRAM (the `:46567` process is the router's own worker child, not a separate load — see the note in "llama.cpp deployment"; do not stop it).
- [x] Confirm the API key no longer appears in `ps aux`/`/proc/PID/cmdline` for the llama-qwen process — it must come from `EnvironmentFile=`/`LLAMA_API_KEY`, not a `--api-key` argument (see "llama.cpp deployment"). **Done 2026-09-12**: verified `--api-key` is absent from the running process's argv, `/etc/default/llama-qwen` is mode 600 owned by `sashi`, and auth is still enforced (401 without the key, 200 with it on `/v1/models`).
- [ ] Confirm GitHub App can read the pilot repository but cannot modify source during Phase 1.
- [ ] Confirm Paperclip persistence across restart.
- [ ] Confirm database backup and test restore.
- [ ] Confirm Hermes workspace cleanup after a task.
- [ ] Confirm audit logs do not contain secret values.
- [ ] Confirm no service can access Docker/Podman socket or privileged host paths.
- [ ] Confirm the Claude Supervisor adapter's Anthropic API key is stored outside Git, scoped to a dedicated service identity, with no GitHub App, Paperclip `task_bridge`/board-token, or `LLAMA_API_KEY` access.

### Policy validation

- [ ] Ensure no agent can merge, deploy, alter secrets, alter workflows, change GitHub administration, or modify its own policy.
- [ ] Ensure issue-open events do not auto-launch a write-capable agent.
- [ ] Ensure only explicit label + Paperclip approval can dispatch an implementation task.
- [ ] Ensure code-writing agents create draft PRs only.
- [ ] Ensure protected paths force human review.
- [ ] Ensure Paperclip/Hermes services are not publicly exposed without an explicit secure access design.
- [ ] Ensure Claude Supervisor output cannot directly modify agent files, policy, or repository content, and cannot call `paperclipai approval approve`/`reject` itself — only produce proposals and approval-request payloads for a human to act on.

### Pilot validation

- [ ] Create the Paperclip task for GitHub Issue #11.
- [ ] Run Hermes in read-only diagnostic mode.
- [ ] Verify the report contains evidence, limitations, confidence, and recommended next action.
- [ ] Verify the system stays within resource limits.
- [ ] Verify no unapproved source modification occurs.

## Final execution recommendation

1. Use `RSA-Data-Solutions/always-on-engineering-fleet` as the version-controlled blueprint for the new platform.
2. Deploy Paperclip and PostgreSQL as the lightweight management plane.
3. Deploy llama.cpp as a loopback-only local inference service using one model server and one concurrent request.
4. Deploy Hermes as an isolated worker with an ephemeral workspace, tool allowlist, network restrictions, and a read-only GitHub App.
5. Import/rewrite current agent and routine definitions into explicit Paperclip roles and Hermes task profiles.
6. Migrate live state out of `fleet-workspace` and into Paperclip/PostgreSQL, CI artifacts, and Hermes audit storage.
7. Use Issue #11 as the first read-only pilot task.
8. Do not permit branch/PR writing until the read-only phase produces reliable, audited, useful results.
9. When ready, allow a separate writer identity to create draft PRs only for approved, low-risk tasks in one allowlisted repository.
10. Keep human approval, protected branches, GitHub Actions, and deterministic policy checks as the final control boundary.
