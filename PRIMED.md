---
target-engine: engine-plato
primed: 2026-08-31-00_59
---

# PRIMED — grill concluded

Stage-A drafts grilled item-by-item 2026-08-31; every ruling is the pilot's.
Sources cite the gentar record @ dfb4138 (paths relative to repo root) unless
named otherwise. Plato rule honored: ideals are prose, no numeric targets —
the conflux interview's numerics (target 0.6, tolerance) died with its deleted
frame and are **not** carried here.

## Intent

- `confirmed` (pilot accepted README.md:3-7 wording) — compose-native test
  arena: installs constellation components onto disposable pilot-machine
  benches, drives real agents (claude-code, codex, agy) through real tasks as
  if they were humans at a terminal, verifies outcomes across reliability,
  stability, security, integration, UX.

## Ideals

- `confirmed` **parallel-matrix** (README.md:186-191; conflux interview
  2026-08-31 as prior art) — the arena runs a whole suite of scenarios across
  several benches in one coordinator invocation; per-scenario verdicts, spans
  and teardown stay honest under parallelism.
- `confirmed` **real-agent-runs** (README.md:186-189; design.md credential-tier
  decision 2026-08-18) — real claude-code (then other agents) driven by the pty
  driver inside a bench through real tasks; credentials reach the bench by a
  decided tier without ever being readable there; verdicts still come from
  reality.
- `confirmed` **substrate-honesty** (design.md:117-134; docs-honesty suites
  README.md:111-112) — the arena carries zero forge dependencies inside it,
  runs anywhere Docker runs, and its own docs stay drift-guarded against
  reality.
- `confirmed` **subject-coverage** (docs/subject-integration.md;
  design.md:35-45) — any constellation component can become a subject with
  minimal moves (scenarios as decisions, ~10-line trigger, nothing else);
  subjects stay mounted, never baked.
- `confirmed` **macos-parity** (README.md:180-184, 212-239) — the tart tier is
  first-class: macOS subject suites run in CI like Linux ones, not only where a
  Mac is manually reachable.

## Seeds

All `confirmed` (pilot accepted the full set):

- **gentar repo itself** — the record and the arena code (PRIMER convention:
  the repository is the first seed).
- **sbx-linux-tier** — sbx sandboxes, per-run microVM, own Docker daemon
  (design.md:183-192).
- **bench-host-142** — VM 142 on arf, 10.10.10.52, runner + host fixes
  persistent (README.md:208-210; TASK.md).
- **bench-templates** — gentar-bench-v1 / gentar-bench-macos-v1, claude-code
  pinned, digest in spans (README.md:155-158).
- **compose-arena** — one compose file, coordinator+telemetry(+dashboard);
  benches over SSH (README.md:39-51).
- **telemetry-spans** — every step an OTel span in ClickHouse; agent OTLP joins
  in one SQL (README.md:159-168).
- **pty-driver** — pexpect over `ssh -tt … sbx exec -t`; gauntlet policies
  ported (README.md:152-155).
- **scenario-toml** — decisions-not-steps declarative suites; 16 live
  (README.md:87-114).
- **tart-tier** — macOS benches as tart VMs on macminim behind the same
  BenchHost interface (README.md:212-239).

## Hints

All `confirmed` (pilot accepted all six; hazards from TASK.md session record):

- `bench-host/sbx-lifecycle` — full programmatic lifecycle. Hazards: young
  version line (0.38→0.39 changed first-run pty behavior — pin + re-verify);
  tar-after-create broke bind mounts (fixed, ordering); auth token rotation
  policy TBD; 10s/call keyring tax closed on VM 142 but must be redone on any
  fresh host.
- `bench-host/tart-tier` — same interface, opt-in per scenario. Hazards: guest
  subnet routed only on the Mac; manual template rebuild.
- `driver/pty-mechanics` — picker navigation, danger gate, auto-approve.
  Hazards: raw-stream transcript, LAST ❯ cursor line, ICRNL Enter-as-\n,
  settle-wait must survive new call sites.
- `ci/forge-agnostic-tiers` — gate / keyword tags / nightly / dispatch, exit
  code is verdict. Hazards: shared egress IP rate limit (pin VERSION); two
  arenas one host need port + teardown discipline; always `--base main`;
  docs-honesty anchors are single-line `grep -qF`.
- `ci/budget-guard` — coordinator-side, spans-fed, refuse-before-bench.
  Hazards: check-then-spend race under concurrency; spend simulated today.
- `subjects/mounted-checkouts` — mounted read-only, never baked. Hazards:
  untracked mounts die with worktree cleanup (rsync, both slashes, no
  symlinks); private-repo clone paths; prctl(PR_SET_NAME) for comm-based
  liveness probes.

## Deferrals

All `confirmed` parked (pilot ruled each stays recorded as parked):

- real-agent runs — API-key injection + credential-tier decision
  (README.md:186-189).
- macOS CI leg — tart suites not gateable from the Linux runner
  (README.md:180-184).
- multi-bench parallel matrices (README.md:190-191).
- Forgejo/Gitea forge swap (designed, not exercised).
- `--kit` evaluation.
- Allure report emitter.
- LXC bench-host.
- CI sizing for matrices (conflux interview 2026-08-31: local first).

## Tensions (recorded, not resolved)

- **real-agent-runs** sits in the ideals (endpoint) and in the deferrals
  (parked work) — the ideal stands; the work is parked. Which unparks first is
  the pilot's, not the record's.
- **parallel-matrix** was the conflux frame's focus (interview 2026-08-31,
  target 0.6) and is now parked again after the engine overrule — the pilot's
  plato interview may re-select it; this file takes no side.

## Ruling trail

Intent, 5 ideals, 9 seeds, 6 hints, 8 deferrals — all `confirmed` by the pilot
in session 2026-08-31; 0 unconfirmed. Handoff crumb:

```
devlooper › prime › done › PRIMED.md on root, 29 confirmed / 0 unconfirmed
next › pilot: claude DEVLOOPER.md
```
