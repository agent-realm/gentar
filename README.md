# gentar

**aGENT ARena** — a compose-native test arena. One repo, one
`docker-compose.yml`; it installs any Ultimagent constellation component onto
disposable "pilot machine" containers, drives real agents (claude-code, codex,
agy, …) through real tasks as if they were humans at a terminal, and verifies
the outcomes across reliability, stability, security, integration, and UX.

Runs anywhere Docker runs: laptop, CI runner, Proxmox host. Proxmox is just
another Docker host.

> Part of the [ultimagent](https://github.com/agent-realm/ultimagent)
> constellation. **gentar is the successor line to
> [agent-gauntlet](https://github.com/agent-realm/agent-gauntlet)** — same
> driver logic and telemetry substrate, ported by copy onto a compose-native
> substrate. agent-gauntlet stays in service for the projects using it;
> subjects migrate to gentar when their owners choose.

## What it does

A component repo (the **subject**) contributes a `gentar/` directory of
scenario configs and feature probes. gentar then:

1. Brings up a **bench** — a disposable container impersonating a pilot's
   machine: agents pre-installed, credentials injected at runtime (never
   baked), the subject *not* installed yet.
2. Renders each scenario's declarative **decisions** (channel, server mode,
   flags, run mode — never steps) into natural instructions.
3. Drives a real agent through them at a **pty** — typing commands, answering
   onboarding prompts, navigating pickers — like a human would.
4. Asserts **verdicts from reality**: files, processes, SQL, spans, TTY
   output. Never "the agent said it worked."
5. Emits every step as an OTel span into ClickHouse; a stateless dashboard
   renders pass/fail with span drill-down.

Multi-component scenarios spawn a nested *stack-under-test* compose project on
an internal network.

## The stack

| Piece | Role |
|---|---|
| `coordinator` | engine: bench lifecycle, scheduling, driver transport, assertions, budget guard |
| `bench ×N` | **sbx sandboxes** (Docker Sandboxes) spawned by the coordinator on a bench-host — per-run microVM, own Docker daemon each; macOS tier: tart VMs |
| `telemetry` | ClickHouse + otelcol-contrib; spans schema ported from agent-gauntlet |
| `dashboard` | stateless verdicts + span drill-down |

Benches are not compose services. The compose file carries coordinator +
telemetry (+ dashboard); the coordinator creates and destroys each bench
over SSH (`sbx create/exec/rm` on Linux, `ssh` for tart macOS VMs).

## Test taxonomy (10 dimensions)

lifecycle · feature/conformance (against
[`ultimagent/contracts/`](https://github.com/agent-realm/ultimagent)) ·
integration · agent-in-the-loop · reliability/chaos · security · UX ·
performance · docs-honesty · compatibility matrix

"Regression" = a suite over any dimension vs. the last known-good baseline.

## Design tenets

- **Subjects stay external and mounted**, never baked into images — the
  per-repo sandbox with a baked checkout is the constellation's retired
  anti-pattern.
- **Configs state decisions, not steps.** The driver renders decisions into
  the natural instruction the agent executes; assertions verify outcomes.
- **The container is the reset.** Every scenario gets a fresh bench; wedged
  runs are discarded, never repaired.
- **Auth discipline.** Credentials are explicit runtime env vars on a
  throwaway; the isolation claim is itself an executable security test.
- **Verdicts from reality + spans.** Agent self-reporting (OTLP from inside
  the bench) joins to assertions in one SQL query.

## CI contract

Tiered, and dead simple: `docker compose up` + exit code is the whole
contract.

| Tier | When | Suites |
|---|---|---|
| PR gate | every pull request | deterministic: lifecycle, conformance, docs-honesty |
| nightly | post-merge | agent-in-the-loop (real LLM calls — slow, costly, flaky → quarantine + budget guard) |
| release | on release | upgrade, security, compatibility matrix |

## Status

Design of record ([docs/design.md](docs/design.md)) and build plan
([docs/buildplan-2026-08-18-v1.md](docs/buildplan-2026-08-18-v1.md))
landed. **Phases 0–3 done**: sbx spike · arena skeleton (compose:
coordinator + ClickHouse + otelcol; benches = sbx sandboxes spawned over
SSH) · TOML scenarios + oracle runner (`claude-playbooks-install` green,
9/9 reality assertions) · **pty driver** — pexpect over
`ssh -tt … sbx exec -t`, gauntlet policies ported (approval
auto-approve, danger gate, picker navigation by ❯ cursor line),
exercised scripted (no LLM): `scripted-onboarding` (answer / pick /
confirm / expect), `scripted-danger` (gate fires before any approval).
First subjects, in order: **claude-playbooks** (the installer CLI) ·
**kommander-playbook** · **memhouse**. macOS tier: **tart** on the
pilot's Mac (`macminim`). Bench home dir is a scenario decision
(`pilot_user` → `/Users/<name>` on macOS, `/home/<name>` on Linux).
Real-agent runs (claude-code in a bench) are next — they need API-key
injection, which is a credential-tier decision, not a code gap.

## Quickstart (phase 1)

Prereqs: a Docker host for the arena, and a **bench-host** — any Linux
machine with `sbx` installed and logged in once (`sbx login`, device
flow; the token persists).

```bash
cp .env.example .env          # point at your bench-host + SSH key
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
docker compose run --rm coordinator run smoke   # exit code = verdict
docker compose exec clickhouse clickhouse-client \
  --user gentar --password gentar \
  -q "SELECT span_name, status FROM gentar.spans ORDER BY ts"
```

Phase-1 defaults point at the spike VM on arf (`10.10.10.200`).
