# gentar build plan — v1 (2026-08-18)

Builds the design of record ([design.md](design.md)) into running code. One
phase = one demonstrable capability; each phase's acceptance criteria are
executable, not narrative. Phase 0 is already complete.

Standing decisions this plan inherits: benches are **sbx sandboxes**
(decision #6, spike-proven on arf); subjects are mounted, never baked;
verdicts from reality; budget guard lives in the coordinator; forge-agnostic
CI contract (`docker compose up` + exit code); subjects in order
**claude-playbooks → kommander-playbook → memhouse**; tart/macminim is the
macOS tier (not on this plan's critical path).

## Implementation choices (made here, veto-able)

- **Coordinator language: Python 3.** The ported assets are Python or
  port cleanly to it — gauntlet's `lib/matrix_gen.py`, dashboard
  `generate.py`; the driver needs `pexpect` (pty); telemetry needs
  `clickhouse-connect`. One language across coordinator, driver, dashboard.
- **First bench-host: VM 9100 on arf** (`gentar-sbx-spike`, 10.10.10.200 —
  logged in, sbx v0.38.0 installed). A cheaper LXC bench-host is a later
  optimization, not a prerequisite.
- **Scenario format: TOML** (`gentar/` dir per design; schema v1 in phase 2).
- **gauntlet port checklist** (what gets copied vs rewritten): telemetry
  spans schema + provenance fields (port verbatim), assert vocabulary
  `file-exists` / `file-contains` / `systemd`/`process` / `sql-count` /
  `text-in-transcript` (port), driver logic `lib/drive.sh` → pexpect
  (rewrite, same policy: picker navigation, danger gate), clone lifecycle
  `lib/vm.sh` (do **not** port — sbx replaces it), `lib/events.sh`
  (replaced by otelcol pipeline).

---

## Phase 0 — bench substrate spike ✅ DONE (2026-08-18)

sbx proven on headless Linux on arf: device-flow auth with persistent
token, `create`/`exec -t`/`cp`/`ls --json`/`rm` lifecycle, custom
templates, workspace bind-mounts, nested Docker with hard isolation,
`shell` agent for no-LLM runs. Report: task artifact
`sbx-spike-2026-08-18-02_41.md`.

## Phase 1 — arena skeleton

**Deliverables**

- `docker-compose.yml`: `coordinator`, `clickhouse`, `otelcol`, `dashboard`.
- Coordinator MVP (Python): bench-host client (SSH → `sbx` commands),
  run loop, span writer (direct ClickHouse insert at first; otelcol wiring
  in phase 5).
- `gentar` CLI entry point: `gentar run <scenario> [--ref] [--suite]`,
  `gentar ls`, exit code = verdict.

**Acceptance** — with the arena up on any Docker host and bench-host
configured: coordinator creates an `sbx shell` sandbox on 9100, execs
`uname -a`, writes one span row to ClickHouse, destroys the sandbox,
exits 0. No LLM, no subject.

## Phase 2 — scenario schema + oracle runner

**Deliverables**

- Scenario schema v1 (`scenarios/*.toml`): `[install]` decisions,
  `[verify]` probe expectations, `[bench]` needs (`nested_docker`,
  `pilot_user`), oracle path.
- Assertion engine v1 (Python port of gauntlet's vocabulary:
  file-exists / file-contains / process / sql-count / text-in-transcript).
- Oracle mode: run the subject's reference solution in the bench, then
  assert.

**Acceptance** — subject #0 (`claude-playbooks`) oracle run green
end-to-end: fresh bench → oracle installs the `claude-playbook` CLI by its
documented path → `claude-playbook install` of kommander-playbook →
assertions on files + `--version` output → PASS with spans. **This is the
manual mini-scenario, promoted to the phase's acceptance test.**

## Phase 3 — pty driver (agent mode)

**Deliverables**

- Driver: pexpect over `sbx exec -t`; decision renderer (decisions →
  natural instruction); gauntlet policies ported (picker navigation by
  cursor line, danger gate on destructive patterns, auto-approve ordinary
  permission prompts).
- Agent adapters: claude-code first (sbx per-agent image), codex second.
- Credential injection, env tier (runtime env on a throwaway bench).

**Acceptance** — agent-driven scenario: real claude-code in a bench
installs kommander-playbook answering its onboarding prompts; assertions
from reality pass; transcript spans recorded; a destructive-command
injection aborts safely (danger gate test).

## Phase 4 — bench template + credential tiers

**Deliverables**

- Bench Dockerfile (pinned agent versions, pexpect, probes toolkit) →
  `sbx template load`; template name/version recorded in spans.
- Security tier: credential-holding egress proxy (keys never in the bench;
  `--deny-network` where it narrows).

**Acceptance** — bench reproducible from a template digest (two creates,
same versions asserted in spans); security-tier scenario proves
use-without-read: agent completes a task needing the key via proxy while a
probe reading the bench's env/files finds no key material.

## Phase 5 — telemetry, dashboard, budget guard

**Deliverables**

- Spans schema port (subject-leading sort key, 18 provenance fields),
  otelcol pipeline (harness + agent OTLP join), dashboard (port gauntlet
  `generate.py`, stateless HTML).
- Budget guard + flake quarantine in the coordinator.

**Acceptance** — one SQL joins harness spans and agent OTLP for a run;
dashboard renders verdicts + drill-down; budget guard refuses a run that
would exceed its cap (simulated spend); a quarantined scenario is skipped,
not failed.

## Phase 6 — CI wiring

**Deliverables**

- `.github/workflows/gentar.yml`: PR-gate (deterministic suites),
  nightly (agent-in-the-loop, behind budget guard), `workflow_dispatch`
  inputs (subject, ref, suite, benches).
- Subject-side integration doc + first subject wired (the ~10-line job).
- Bench-host runner registration (arf), concurrency groups, per-run
  compose project names.

**Acceptance** — a PR on the wired subject repo triggers the deterministic
suite green from CI; a dispatch run against an arbitrary ref works; nightly
fires and respects the budget.

## Phase 7 — subject onboarding wave

**Deliverables**

- `kommander-playbook` scenarios (install / update / task-lock guard).
- `memhouse` scenarios (port gauntlet's memory-house matrix as the
  reference; it is the deepest existing corpus).
- Docs-honesty suite v1 (README claims vs reality).

**Acceptance** — all three subjects have green oracle suites; ≥1
agent-driven suite runs nightly; one upgrade scenario (old release → new)
passes.

---

## Deferred (explicitly not in v1)

- tart/macOS tier wiring on macminim (design hooks exist; no phase).
- Gitea/Forgejo forge swap (portability is designed, not exercised).
- Kits evaluation (`--kit`), Allure emitter, LXC bench-host, multi-bench
  parallel matrices (coordinator supports it; CI sizing comes later).
- agent-gauntlet repo archive + `_archived/` move — trigger: end of
  phase 5 (telemetry + driver fully ported).

## Risks / watch items

- sbx is young (v0.38.0, kits experimental) — pin the version in the
  bench-host definition; re-verify on upgrades.
- Auth is a Docker account (device-flow once per bench-host) — token
  rotation/expiry policy TBD; if Docker gates sbx behind paid governance
  later, the fallbacks (DinD/sysbox) remain designed.
- LLM spend — oracle-first ordering keeps every phase before 3 free.
