# Changelog

All notable changes to gentar are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Versioning — what the number promises

Pre-1.0 semantic versioning. Within a minor version (`0.1.x`), two things
are stable and will not break:

- **the scenario TOML schema** — a suite written against `0.1.0` still
  loads and means the same thing on any `0.1.x`;
- **the exit-code contract** — `0` pass, `1` fail, `2` usage/config
  refusal, and a refusal always happens before a bench is created.

Everything else is internal: engine module layout, span attributes,
report markdown, bench-tier implementations, the dashboard's HTML, and
every `GENTAR_*` default. A minor bump (`0.2.0`) may change the schema;
read this file before moving an adopter's `GENTAR_REF` across one.

Adopters pin a release tag, not a branch.

## Unreleased

## 0.1.0 — 2026-09-22

First release. The arena runs standalone: one compose file, four bench
tiers, 22 suites, exit code as the verdict.

### End-to-end test runner

- Compose-native arena — coordinator, ClickHouse, otelcol and dashboard
  in one `docker-compose.yml`. Benches are not compose services: the
  coordinator mints one per run and destroys it.
- Declarative TOML scenario schema v1 — subject, bench tier, template,
  credentials, `[oracle] steps`, `[driver] turns`, `[budget]`, and
  `[[verify.files]]` / `[[verify.commands]]` assertions.
- Exit code is the verdict: `0` pass, `1` fail, `2` usage/config
  refusal. Refusals (unknown scenario, missing credential, over-budget)
  happen before any bench is created.
- Four bench tiers behind one interface: `sbx` Docker Sandboxes microVMs
  (default, nested Docker per bench), `tart` macOS VMs, `osb`
  OpenSandbox containers driven entirely over HTTP/WebSocket, and
  `daytona` cloud sandboxes over an expiring-token ssh gateway.
- Deterministic bench templates — `bench-template/build.sh` snapshots a
  template with the agent CLI pinned by `bench-template/VERSION`; the
  `bench.create` span records template tag and image digest.
- Telemetry: every step is an OTel span in ClickHouse with 14 provenance
  attributes, plus a `latest_scenario_status` view. Software inside a
  bench can self-report OTLP that joins harness spans on `run_id` in one
  SQL query.
- Stateless dashboard — `docker compose run --rm dashboard` renders one
  self-contained HTML file of verdicts with span drill-down.
- Guards in the engine, not in forge features: a budget guard
  (`GENTAR_BUDGET_CAP` against each scenario's declared spend,
  accumulated from past runs' spans) and a flake quarantine
  (`GENTAR_QUARANTINE`) that skips rather than fails.
- `bin/arena` — the local entry point that cannot strand a stack. Every
  service starts as a one-off `compose run -d --rm` for daemon-level
  `AutoRemove`, `compose.rm.yml` makes the ClickHouse volume anonymous,
  and a trap tears the project down on every exit path. `bin/arena gc`
  collects arenas stranded by older runs.

### Reviver

- Every terminal outcome — pass, fail and refusal alike — writes
  `out/report-<run_id>.md`: header table, reproduce command, every step
  with its exit code and output tail, every assertion with what it
  expected and what reality showed, the pty transcript when a driver
  ran, and the summary.
- Reports carry credential **names**, never values, and are safe to hand
  to an agent or a human. Writing one is best-effort and can never
  change a verdict.

### Pilot simulator

- pty driver over the bench's terminal with scripted turns: `answer`,
  `expect`, `pick` (❯-cursor picker navigation), `key` (raw key events,
  optionally anchored to a screen and paced), `abort`.
- Cell-model screen reconstruction — the driver replays the pty stream
  through a terminal cell model rather than tailing bytes, because a
  diff-rendering TUI re-sends only changed cells. Unit-tested in
  `coordinator/tests/test_render.py`, which runs in the coordinator
  image build.
- Danger gate — the driver aborts rather than approving a prompt whose
  command matches the destructive pattern. Enforced by the
  `scripted-danger` gate suite, not by documentation.
- Runtime credential injection, never baked. Declared entries are
  alternatives and a list entry is an all-of group, so a token without
  its endpoint refuses (exit 2) instead of starting a misconfigured
  bench. Only the winning group is forwarded. Any Anthropic-protocol
  endpoint works.
- `agent-pty-smoke` — a real `claude-code` TUI driven through its whole
  first run (theme, declining the sandbox's placeholder key, confirm
  footer, intermittent security notes, trust folder,
  bypass-permissions) and a task; the verdict is a byte-exact `cmp` of
  the file, never the agent's reply.
- `agent-smoke` — the headless real-agent path, provider-agnostic, with
  an optional cheaper-model pin forwarded via `pass_env`.
- `agent-profile-smoke` — a real agent running under a configuration
  install pinned to the newest release tag, so the ref under test is
  never its own tool; triple reality verdict.

### Infrastructure

- 22 suites: 20 TOML files plus the `smoke` and `smoke-fail` built-ins,
  covering bench lifecycle, the four substrates, template pinning,
  telemetry join, budget refusal, driver mechanics, the danger gate,
  three real-agent tiers, subject install/update/lock suites, a real
  deployed service inside a bench, and docs-honesty for two subjects
  including this repo.
- CI tiers in `.github/workflows/gentar.yml`: a six-suite PR gate;
  keyword tags (`arena`, `arena-<scenario>`, `v*`) that run the gate at
  any commit; a nightly subject sweep behind the budget cap; and
  `workflow_dispatch` at an arbitrary engine and subject ref.
- Release proof — a `v*` tag runs the full gate, and a guard fails the
  job if the tag does not equal `v$(cat VERSION)`.
- Adoption kit — `subject-template/` is a copyable `gentar/` directory
  (commented scenario, runner, bench-less dry-run replay, workflow) with
  the contract in `docs/subject-integration.md`. Subjects mount, never
  bake.
