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

## Open decisions

| # | Question | Notes |
|---|---|---|
| 1 | Driver transport: docker exec vs sshd-in-bench | exec is simpler; sshd preserves the gauntlet driver's ssh-shaped assumptions |
| 2 | CI credential scoping | which secrets reach which bench; per-run throwaway keys |
| 3 | No-LLM smoke variants | cost control: deterministic near-equivalents of agent-in-the-loop scenarios |
| 4 | macOS-fidelity backend | optional, not a blocker |
| 5 | agent-gauntlet retirement mechanics | and its TERMINOLOGY.md entry |

## Provenance

- Forked from task `agent-gauntlet` 2026-08-17-13_29; design conversation
  logged in that task's `sessions/2026-08-17.md`.
- Name **gentar** (aGENT ARena) coined by the pilot 2026-08-17; verified free
  in `ultimagent/TERMINOLOGY.md` (canon entry pending — names live in the
  canon, not in habit).
