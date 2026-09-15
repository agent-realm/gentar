# gentar — design

The architecture as agreed at the fork (2026-08-17, worked out in the
agent-gauntlet parent session; carried here so the repo is self-contained).
This is the plan of record until a spike says otherwise.

## Why

agent-gauntlet proved the pattern — declarative decisions, human-simulation
driver, OTel-shaped telemetry, reality-based assertions — on a Proxmox VM
substrate. That substrate is the expensive part and the fragile part: clone
lifecycle, sudoers, ZFS snapshot ladder, credential sync, plus two open wounds
(the vzdump durability gap and the `/etc/environment` token-leak class).
testbed is already a Linux approximation of a macOS home, so a container is
no less faithful than the VM was. Replacing VMs with a single Docker Compose
stack deletes the whole apparatus, both known gaps, and makes the engine
runnable anywhere.

gentar supersedes agent-gauntlet as the constellation's shared test engine.

## Architecture

One repo, one `docker-compose.yml`:

| Service | Role |
|---|---|
| `coordinator` | engine: matrix expansion, scenario scheduling, driver transport, assertion runner |
| `bench ×N` | disposable pilot machine: agents pre-installed, auth injected at runtime — never baked; TTY via pty; subject NOT installed at start |
| `telemetry` | ClickHouse + otelcol-contrib |
| `dashboard` | stateless: verdicts + span drill-down |

Multi-component scenarios spawn a nested *stack-under-test* compose project on
an internal network.

### Subjects

A subject = a component repo contributing a `gentar/` directory:

- scenario configs stating install **decisions** (channel, server mode, flags,
  run mode) — never steps
- feature probes

Subjects are **mounted, never baked** into images. The per-repo sandbox with a
baked checkout is the retired anti-pattern; gentar exists partly to enforce
its retirement.

### Driver

The coordinator impersonates a human at the bench's pty — typing commands,
answering onboarding prompts, navigating pickers. Driver logic ports from
agent-gauntlet (`lib/drive.sh` heritage); only the transport into the bench
changes.

### Verdicts

Assertions run against reality: files, processes, SQL, spans, TTY output.
Never agent self-report alone. Agent self-reporting (OTLP from inside the
bench) joins to assertions in one SQL query.

### Telemetry

The spans schema, subject-leading sort key, 18 provenance fields, and OTel
pipeline port verbatim from agent-gauntlet.

## Test taxonomy (10 dimensions)

lifecycle · feature/conformance (against `ultimagent/contracts/`) ·
integration · agent-in-the-loop · reliability/chaos · security · UX ·
performance · docs-honesty · compatibility matrix

"Regression" = a suite over any dimension vs. the last known-good baseline.

## CI tiers

- **PR gate (deterministic):** lifecycle, conformance, docs-honesty.
- **Nightly/post-merge (agent-in-the-loop):** real LLM calls — slow, costly,
  flaky — with quarantine + budget guard.
- **Release:** upgrade, security, compatibility matrix.

`docker compose up` + exit code is the whole CI contract.

## What gets deleted from agent-gauntlet

- All Proxmox coupling: clone lifecycle, sudoers, ZFS snapshot ladder,
  credential sync.
- The vzdump durability gap.
- The `/etc/environment` token-leak class — in gentar the credential is an
  explicit runtime env var on a throwaway, and the isolation claim becomes an
  executable security test.

## Reuse map (decided 2026-08-17)

Don't invent wheels that exist; build only the arena core. Survey of the OSS
landscape found no product whose subject is *a product installed and used by
an agent impersonating a human* — eval frameworks (Inspect, Vivaria,
terminal-bench) evaluate **agents**; CI frameworks schedule **commands**.
gentar inverts both: the agent is the simulated user, the product is under
test.

**Wheels adopted (proven OSS, embed as-is):**

| Wheel | Used for |
|---|---|
| Docker Compose | arena substrate + nested stack-under-test; makes the arena forge-agnostic (`compose up` + exit code) |
| otelcol-contrib + ClickHouse | telemetry substrate (ported schema from agent-gauntlet) |
| pexpect / tmux control mode | pty primitives for the human-simulation driver |
| **tart** (Cirrus Labs) | macOS bench backend — macOS VMs on Apple hardware, when a scenario needs real macOS |
| **terminal-bench / harbor** patterns | agent adapters (claude-code, codex, agy → bench pty) and the **oracle-solution** concept = no-LLM smoke variants |
| anthropics/claude-code-action | PR auto-review/fix loops (subject repos' own CI; separate concern from the arena) |
| Allure (optional) | report format emitter for familiar test-report UX |

**Core built (the missing wheel — ports from agent-gauntlet):** bench
lifecycle, decisions-not-steps scenario renderer, pty impersonation policy,
reality-based assertions joined with spans in one SQL, budget guard +
flake quarantine.

## Forge-agnostic trigger layer (decided 2026-08-17)

The arena has zero GitHub dependencies inside it. The forge (GitHub now;
Gitea/Forgejo both viable later) is only the button. Two rules keep it
portable:

- **Budget guard + quarantine live in the coordinator**, not in forge
  features (GitHub "environment protection" has no Gitea/Forgejo
  equivalent — and the coordinator owns the spend SQL anyway).
- **Subject integration is the compose contract, not `workflow_call`:** a
  subject's CI job is ~10 lines — checkout subject, run gentar's compose
  with the checkout mounted. Identical on GitHub, Gitea, Forgejo, Jenkins,
  cron, or a laptop.

Runners must exist on whatever metal we use (self-hosted runner in an LXC on
arf for Linux benches; a runner on a Mac for the tart/macOS tier — macOS
VMs require Apple hardware, Proxmox cannot host them). Runners connect
outbound only (polling); no inbound ports.

## Open decisions

| # | Question | Notes |
|---|---|---|
| 6 | ~~Nested-Docker vehicle~~ **DECIDED by spike 2026-08-18: Docker Sandboxes (sbx)** | All unknowns resolved live on arf (VM 9100, Ubuntu 24.04, nested KVM): headless device-flow auth with on-disk persistent token; full programmatic lifecycle (`create`/`exec -t` pty/`cp`/`ls --json`/`rm`, `run -d`); custom templates (`-t`, tar load); workspace bind-mounts + `--clone` git wiring; **a full Docker Engine inside each sandbox** with hard two-way isolation from the host daemon; egress under policy; `shell` agent = no-LLM oracle vehicle; per-agent default images (claude, codex, …). Spike report: task artifact `sbx-spike-2026-08-18-02_41.md` |
| 7 | CubeSandbox as a fourth bench tier? **CANDIDATE — recorded 2026-09-15, not spiked** | RustVMM/KVM microVM service with an E2B-compatible API and an L7 egress proxy with per-request credential injection ([TencentCloud/CubeSandbox](https://github.com/TencentCloud/CubeSandbox), v0.7.0). Would combine what the two Linux tiers split: sbx's microVM isolation with osb's API drive. The one unmet need it maps to is the deferred security-tier credential-holding proxy (decided 2026-08-18 below) — no live consumer until real-agent/security-tier work starts. Headless CI microVM is already covered (sbx gate green on VM 142). Revisit trigger: security-tier work begins. Spike checklist (KVM on the host, API lifecycle incl. pty, Docker-in-microVM, custom templates, proxy credential opacity, density/boot-time vs sbx, v0.x API stability) lives in the handoff: task artifact `handoff-cubesandbox-2026-09-15-07_45.md`. Do not use tr0 for any of it (pilot constraint). |
| 8 | ~~Agent credential provider~~ **DECIDED 2026-09-15: provider-agnostic alternatives** | Tier-1 credential guard treats declared env-var names as ALTERNATIVES, not conjunctions — refuse (exit 2) only when none is present. `ANTHROPIC_API_KEY` (first-party) or `ANTHROPIC_AUTH_TOKEN`+`ANTHROPIC_BASE_URL` (any Anthropic-protocol endpoint — GLM coding plan at `https://api.z.ai/api/anthropic` proven live in agent-smoke, routers, proxies); claude-code reads both natively, z.ai accepts claude-* model IDs (no model pin). Verified end-to-end: bench egress to z.ai, real run PASS host-side + in compose with spans, refusal path exit 2. **Cheaper-model pin (2026-09-15):** scenarios carry optional `pass_env` (non-guard passthrough); agent-smoke pins `ANTHROPIC_DEFAULT_SONNET_MODEL` (repo var) — slot vars accept glm-* IDs the main-model path's catalog rejects (glm-5.3-flash hard-fails as `ANTHROPIC_MODEL`, works as the sonnet slot, proven live). |

Decided 2026-08-17: ~~no-LLM smoke variants~~ → oracle-solution pattern
from terminal-bench (every scenario ships a reference solution; the smoke
variant runs the oracle instead of an agent). ~~macOS-fidelity backend~~ →
tart on a Mac runner; default remains the Linux-approximation bench.

Decided 2026-08-18: ~~CI credential scoping~~ → **tiered credentials**
(pattern stolen from Docker Sandboxes' proxy injection): cheap deterministic
tiers get explicit runtime env vars on a throwaway bench; the **security
tier routes bench egress through a credential-holding proxy** — keys are
injected per-request at the proxy and never exist inside the bench's
filesystem or environment, making "use-but-not-read" (keyhouse pattern)
literally true and executably testable. Considered and rejected as a
substrate: Docker Sandboxes itself (interactive CLI, no custom images, no
custom networks, no headless CI) — wrong shape for the arena.

Decided 2026-08-18: ~~driver transport~~ → **one transport interface, two
implementations**: `docker exec` for Linux benches (no sshd to run), `ssh`
for tart VMs. The interface pays for itself the moment the macOS tier
exists, and survives any nested-Docker vehicle choice unchanged.

Decided 2026-08-18: ~~agent-gauntlet retirement~~ → mechanics recorded on
its card (umbrella PR #9): port telemetry substrate + driver logic into
gentar first, then archive the GitHub repo and move the checkout to
`_archived/` (the memory-house precedent). Canon entry: gentar card in
`ultimagent/components/`.

Decided 2026-08-18: **bench shape** — the pilot home dir is a scenario
decision: `pilot_user` renders as `/Users/<name>` on the macOS backend and
`/home/<name>` on Linux (path-keyed session data stays valid; the testbed
convention, generalized). **macOS tier is in scope now**: tart runs on the
pilot's Mac (`macminim`) behind a `[gentar, macos]` runner. **First
subjects, in order:** claude-playbooks (the installer CLI) ·
kommander-playbook · memhouse.

Decided 2026-08-18: **per-run nested Docker boundary** (the pattern; vehicle
open as #6) — when a scenario lets the agent fire containers on demand,
those containers are born inside the bench's *own* Docker daemon, never the
arena's: the agent gets root over a throwaway daemon and provably cannot
touch the host's, cross-run container/port/image collisions are impossible,
and a wedged environment is discarded wholesale.

Decided 2026-08-18 (spike, resolves #6's vehicle): **benches are sbx
sandboxes, not compose services.** The compose file keeps coordinator +
telemetry + dashboard; the coordinator spawns benches as sbx sandboxes on a
bench-host (a VM or LXC with Engine + sbx, logged in once via device flow).
Each bench = its own microVM with its own Docker daemon — the nested
boundary comes free. Driver transport becomes `sbx exec -t` (Linux benches)
+ `ssh` (tart macOS tier) behind the same interface; sbx's per-agent
default images replace part of the terminal-bench adapter work; DinD/sysbox
and apple/container-in-tart drop to fallbacks only. tart on macminim
remains the macOS backend (sbx itself cannot host macOS sandboxes).

## Provenance

- Forked from task `agent-gauntlet` 2026-08-17-13_29; design conversation
  logged in that task's `sessions/2026-08-17.md`.
- Name **gentar** (aGENT ARena) coined by the pilot 2026-08-17; verified free
  in `ultimagent/TERMINOLOGY.md`; canon entry landed as the
  `components/gentar.md` card (umbrella PR #9, 2026-08-18).
