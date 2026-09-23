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

## 0.4.0 — 2026-09-23

**The run policy.** Which suites run when is decided once, at adaptation,
and then automated — the pilot's policy, shaped with the first adopter
(claude-playbooks):

- **Phase 1** on every pull request and every push to the default branch:
  bench-free checks on a GitHub-hosted runner (`gentar/run.sh --check`),
  plus a floor of cheap suites on the bench for pushes — and for PRs only
  when the policy allows PR code on the self-hosted runner.
- **Phase 2**, the full regression, only on a dispatch, the `arena` tag or
  a `v*-rc*` tag, as the job `arena / phase2`.
- **A release is gated**, not tested after: `gentar/release-gate.sh <sha>`
  refuses unless that exact commit has a green `arena / phase2`.

No change to the scenario schema or the exit-code contract. What changes is
the kit, which is why this is a minor bump.

### Added

- `gentar/policy.toml` (the subject's) and `gentar/plan.py` (the kit's, its
  only reader). `plan` maps an event to `checks` / `bench`
  (`none`·`targeted`·`phase2`) / `suites`; an unknown key, trigger or suite
  is refused with exit 2, never defaulted. Without a policy.toml the kit
  behaves as 0.3.x did. `gentar/run.sh --plan` shows it for any event.
- `gentar/run.sh --check` — stage the engine, lint the adaptation (a flat
  credential list holding an endpoint; a kit file that differs from the
  pinned engine's copy), dry-run every suite. A fork's PR, which gets no
  secrets and so cannot stage a private engine, is a named skip.
- `gentar/release-gate.sh` — names what it found when it refuses: a failed
  phase 2, a cancelled one, or a run GitHub cancelled before any job
  started. Optional `[phase2] max_age_days`.
- `gentar/hooks.py` — the dry-run hooks (`prepare()`, `HIDE_FROM_PATH`,
  `SKIP_STEP_SUBSTR`) move out of `dryrun.py`, so every kit file can stay
  byte-identical to the kit.

### Changed

- **The kit workflow** is built around a `plan` job on ubuntu-latest; the
  `checks` job is GitHub-hosted too, and only the `bench` job is
  self-hosted. It runs only when the plan asks and never for a fork's PR
  (checked from GitHub's context, not from the PR's files). It triggers on
  pushes to every branch, since only the planner knows which one is the
  default (main, master, trunk…); anything else plans to nothing. Host ports and
  the budget cap come from repository variables, so the file needs no
  edits. So does the engine ref: `vars.GENTAR_REF` overrides `run.sh`'s pin
  on every event, which is how an adopter proves an untagged engine in CI
  before it is released (claude-playbooks: the pin cannot be edited without
  failing `--check`, and a dispatch only exists once the workflow is on the
  default branch).
- **Arenas of one repo are serialised on the host, not by GitHub.** A
  repository-wide concurrency group CANCELS a pending run when a newer one
  queues, so phase 2 and keyword runs were silently dropped behind ordinary
  main pushes (claude-playbooks, observed). `run.sh` now takes a host lock
  per `arena-<subject>` — flock, or a mkdir lock with stale-holder
  detection on macOS — and a later run waits, saying for whom. Locks live
  in a shared, non-sticky `gentar-locks/` directory, so any runner user
  can clear a dead run's lock; one it cannot remove is named with the
  command to remove it, never hung on. The
  workflow's group is per-ref, for dedup only. `--down` never tears down an
  arena another live run holds.
- The workflow's bench-key guard treats a whitespace-only secret as blank,
  agreeing with `run.sh` (claude-playbooks).
- **The dry-run describes a bench, not its host** (claude-playbooks, first
  CI run of `--check`). `prepare()` runs only for suites with a step it
  stands in for (a `SKIP_STEP_SUBSTR` match; a repo declaring none keeps
  prepare-for-every-suite) — its build no longer shadows what an unrelated
  suite installs. And a host whose system install dirs are writable (a
  hosted runner's `/usr/local/bin`, an Intel Mac's) is warned about locally
  and refused in CI: an install there writes outside the scratch home and
  passes or fails for the host's reasons. The kit's `checks` job makes the
  hosted runner bench-like (system bin dirs root-owned, 0755) first.
- `dryrun.py` reports an UNVERIFIED-only suite without failing when run by
  `--check`: those turns need the arena, and a check that always fails is
  a check people learn to ignore.

### Fixed

- The kit README claimed the dashboard shows "the agent's own telemetry".
  No agent CLI writes the self-report relay, so that panel is empty for an
  agent suite; the sentence now says so (claude-playbooks).

### Upgrading from 0.3.x

1. Re-copy `run.sh`, `dryrun.py`, `plan.py`, `release-gate.sh` and the
   workflow from the `v0.4.0` kit. Do not edit them.
2. Move your `prepare()` / `HIDE_FROM_PATH` / `SKIP_STEP_SUBSTR` into
   `gentar/hooks.py` (start from the kit's).
3. Write `gentar/policy.toml` (start from the kit's): the floor, whether a
   PR may use the bench, any `[phase1] setup` toolchain.
4. Port pins you had in the workflow become repository variables
   `GENTAR_CLICKHOUSE_HOST_PORT` / `GENTAR_OTLP_HOST_PORT`; `GENTAR_FLOOR`
   becomes `[phase1] floor`.
5. Add `gentar/release-gate.sh` as the first job of your release workflow.
6. `gentar/run.sh --check` must say `check: clean`.

## 0.3.1 — 2026-09-23

Fixes only, from the first adopter's re-adaptation to 0.3.0
(claude-playbooks) and one gap of the engine's own. No change to the
scenario schema or the exit-code contract; an adopter re-copies the kit.

### Fixed

- **A cancelled CI job left its bench sandbox on the shared bench-host.**
  The coordinator removes its sandbox when a scenario ends; a job
  cancelled mid-bench never gets there, and teardown only *reported*
  strays. CI now gives every job its own `GENTAR_NAME_PREFIX`
  (`g<repository_id>-<run_id>-a<attempt>-<job><index>`: GitHub promises
  run ids unique only within a repository) and teardown runs the new
  `bin/bench-reap`, which removes exactly the sandboxes and workspaces
  whose whole name is that prefix plus the coordinator's run-id shape —
  including a workspace whose sandbox was never created, since sbx pushes
  before it creates. `…-123-…` never matches `…-1234-…`; attempt 2 never
  reaps attempt 1; the unscoped default prefix is refused. It takes the
  bench settings from `docker compose config` — what compose resolved
  for the coordinator, `.env` interpolation, comments and relative paths
  included — and falls back to the shell only without compose. In the kit,
  `gentar/run.sh --down` reaps when the prefix is set and does not touch
  the bench-host when it is not (every local run). Proven by SIGKILLing a
  live coordinator mid-bench and reaping the stranded sandbox, with a
  same-shaped decoy left untouched.
- **`GENTAR_NAME_PREFIX` never reached the coordinator.** The compose file
  did not forward it, so the knob in `.env.example` did nothing. It is
  forwarded now, and an empty value reads as the default. On the sbx
  tier (the only one whose sandbox NAME starts with it), a prefix sbx
  cannot use in a name (CI embeds the GitHub job id, which may hold `_`)
  is refused with exit 2 before any bench exists, rather than failing
  every create; it is not mapped, since `a_b` and `a-b` would then share
  a prefix and reap each other's benches. (claude-playbooks.) So is one
  over 41 characters: sbx rejects a name over 64 (measured; its help does
  not say) and the run id appends 23.
- **`bin/arena`'s bench-key check did nothing on macOS.** It read the
  key path compose resolved with a BRE using `\|`, which BSD sed does not
  support, so it matched nothing and fell back to the shell variable: a
  bad path set only in `.env` reached Docker's mount error instead of the
  exit-2 refusal that names it. Now `sed -E`.
- **The dashboard read the wrong ClickHouse** when an adopter had moved
  the port: it defaulted to 8123 and ignored `GENTAR_CLICKHOUSE_HOST_PORT`
  — on a host where another arena holds 8123, it rendered *that* arena.
  It now follows the host port unless `GENTAR_CLICKHOUSE_URL` is given.
- **The dashboard could not run on a host.** Its default output was
  `/out/dashboard.html`, the compose container's mount; run on a host
  there is no `/out`, and a non-root user cannot create one. Outside the
  container it now writes `dashboard/out/dashboard.html` — the same
  place the container's mount lands — and the kit's printed command
  passes `--out gentar/reports/dashboard.html`.
- **The dashboard logged an HTTP 404 on start.** That is ClickHouse's
  unknown-table answer while the arena is still creating its schema; it
  now says it is waiting.

### Kit

- `GENTAR_KEEP_ARENA=1` prints `gentar/run.sh --down` instead of two raw
  docker commands, and the dashboard command to watch the run — with the
  ClickHouse port compose actually published, so a port moved only in the
  arena's `.env` is not printed as 8123.
- The kit README documents the dashboard (it was undiscoverable from an
  adopter's repo), and no longer says the subject name lives in `run.sh`.
- The workflow's cost comment no longer calls its concurrency group
  per-ref; it is one per repository.
- `HIDE_FROM_PATH` covers the second reason to hide a name: a host tool
  the subject CALLS that a bench does not have.
- Documented: a tag push runs the tagged commit's workflow even before it
  is on the default branch, which is how an adoption PR gets a CI arena
  before merge.
- `GENTAR_REF` pins `v0.3.1`.

## 0.3.0 — 2026-09-23

The first real adoption. claude-playbooks adapted gentar v0.2.0 into a
repo it actually ships, ran it in CI, and patched a dozen kit defects in
its own copy — patches it would have had to re-apply on every engine
bump. Every one is fixed here, and each was reproduced before it was
fixed. Three of them could make a result lie.

Also ships two changes that were reviewed as their own PRs but never
tagged on their own: pull-request narrowing (#34) and a dry-run that
works on the python an adopter actually has (#35).

### Fixed — results that could lie

- **A cancelled run reported success.** Signal traps tore down and then
  *returned*, so bash resumed the script: the next suite started against
  a torn-down arena and the run ended with status 0. A CI cancel is a
  SIGTERM to the shell, so a cancelled run read as a pass. INT and TERM
  now exit 130/143, in `bin/arena` and the kit. (Earlier signal tests
  signalled the whole process group, where the child dies with 130 and
  hides it.)
- **The dry-run could modify the pilot's machine.** One scratch home was
  shared across suites and PATH fell through to the real one, so after
  an uninstall suite, the next suite ran the pilot's *installed* CLI —
  which created launchers in the real `~/.local/bin`. Every suite now
  gets a fresh home, and runs on a PATH sealed against the subject's own
  executables: whatever `prepare()` installed is hidden automatically,
  `HIDE_FROM_PATH` adds the rest.
- **A declared credential was dropped silently.** A flat
  `["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]` means *either one*;
  the token won alone and the URL never reached the bench, surfacing as
  "Invalid API key". Forwarding is unchanged (only the winning group
  travels), but the engine now names a set-but-dropped credential in the
  log and in a new report **Warnings** section.

### Fixed — adoption that could not work

- **No adopter's CI could have run.** The kit workflow never passed
  `GENTAR_BENCH_HOST`/`GENTAR_BENCH_USER`, and the engine has shipped no
  bench-host since 0.1.0. They now come from repo secrets, and the
  workflow refuses an unset or placeholder host, or an unset
  `BENCH_SSH_KEY`, before staging anything.
- **A blank bench key passed every check.** `printf '%s\n'` of an unset
  secret writes a one-byte file that passes `-r` and `-s`, then fails at
  ssh. The key must now be non-blank.
- **The subject name was wrong in a git worktree** — it came from the
  directory, which a worktree names after the branch. It is now read from
  the scenarios' `subject =` and refuses the template's `REPLACE-ME` or
  scenarios that disagree. `GENTAR_SUBJECT` overrides.
- **Parsing a `key` driver turn needed pexpect**, so such suites failed to
  load in the dry-run on a host without it. The key vocabulary moved to a
  leaf module.

### Fixed — correctness and noise

- The frozen version used `git describe --tags`, which returns the nearest
  tag of any kind — the floating `arena` trigger could become the version.
  Now `--match 'v*'`.
- Switching `GENTAR_REPO_URL` to a fork with its own same-named tag failed
  the fetch, reported as "GENTAR_REF not found". Now fetched with `--force`.
- The workflow's concurrency group was per-ref while every run shares one
  compose project and one set of ports. Now constant per repository.
- `--review` listed every file under `cmd/` — a Go CLI's implementation,
  27 names burying one real gap. Candidates are now files with the
  executable bit, plus `bin/`.
- The kit ignores `__pycache__/` and `*.pyc`; dry-run scratch homes of
  passing suites are deleted (the old dry-run leaked one per run).

### Changed — security

- The kit workflow's `pull_request` job runs only PRs whose head is in the
  same repository. On a **public** repo that is not enough on its own — a
  fork can add its own workflow aimed at the self-hosted runner — and the
  workflow, both kit READMEs and `AGENTS.md` now say so: require approval
  for all external contributors, or drop the trigger.

### Added

- **A pull request can narrow its own arena run.** A `gentar: <suites>`
  line in the PR body picks the suites; `GENTAR_FLOOR` (a repo variable)
  names suites that run whatever the body says. The bench-host is one
  shared machine, so without this a README typo and an install-path
  rewrite cost the same wall-clock — and an expensive tier that makes
  every PR slow is a tier people stop running.

  **Declared, not inferred.** A rule that reads the diff and picks for
  you fails by silently excluding the suite that mattered: a green PR
  that never tested the change, which is the one outcome this engine
  exists to refuse. A human narrowing on purpose is visible in the PR and
  reviewable like any other claim in it. The floor means a too-narrow
  pick costs coverage on the slow tier, never on the fast guard rails,
  and only pull requests narrow — the default branch and `v*` tags run
  everything, so nothing a PR skipped stays skipped.

  A suite name is `[A-Za-z0-9._-]`; anything else on that line is
  refused with exit 2 before a bench is spent. A PR body is text a
  stranger can write, and it reaches the runner through step `env`,
  never `${{ }}` interpolation into the script body.

- The dry-run runs on python 3.9/3.10 with `tomli` (the same parser
  as stdlib `tomllib`, under its pre-stdlib name), and says exactly what
  to install when neither is present.
- `gentar/run.sh --sweep` — every suite whose credentials are present,
  decided by the engine's own grouping; the rest skipped by name.
- `gentar/run.sh --down` — tear down this subject's arena; the project
  name is derived in one place.

`AGENTS.md` gains the credential-grouping rule, the public-repo warning
for decision 2, the three required CI secrets, and "a local pass is not a
CI pass". No schema or exit-code change: a suite written against 0.1.x
runs unchanged.

## 0.2.0 — 2026-09-23

Adaptation is a process, and this release adds the part that was missing:
a way to notice when a repo has outgrown its suites.

### Added

- **`gentar/run.sh --review`** in the adoption kit. Lists what the repo
  ships that no suite mentions, and the diff since the scenarios last
  changed. Needs no engine, no Docker and no bench; it reports and
  stops, never failing and never writing.

  The case it exists for has no failure of its own: a repo grows a
  command or an install step, the existing suites still pass because
  they never mentioned it, and the board stays green while coverage
  decays. Running the suites cannot catch that — someone has to look.

  It deliberately stops short of deciding. A gap is a question, not a
  defect: some deserve a suite and some never will, and telling them
  apart needs someone who has read the repo. `AGENTS.md` carries the
  agent's half of that job, including the check's blind spot — it
  compares names, so a behaviour change inside a file a suite already
  mentions does not show up.

### Changed

- `AGENTS.md` gains a "Reviewing an adaptation" section, which also
  names the distinction the word "refresh" obscures: **the arena cannot
  go stale** — it is rebuilt every run, every container is `--rm`, and
  benches are disposable. Only the adaptation drifts.
- The kit's `GENTAR_REF` default moves to `v0.2.0`.

No schema or exit-code change: a suite written against 0.1.x runs
unchanged.

## 0.1.1 — 2026-09-23

Post-release fixes. No schema or exit-code change: a suite written
against 0.1.0 runs unchanged.

### Added

- **LICENSE** (MIT). 0.1.0 shipped without one — the file landed after
  the tag was cut — so the version adopters pin carried no terms. That
  is the reason this release exists.
- Refusal-path coverage in the test suite. Three of the defects found
  reviewing 0.1.0 had shipped past a fully green board because no gate
  suite ever took a refusal path; `RefusalPathCoverageTest` now runs the
  real coordinator for the name-level refusals with the bench factory
  booby-trapped, so "refused before any bench exists" is asserted
  rather than assumed (tests 54 → 57).

### Changed

- The nightly and dispatch jobs no longer clone subject repos by
  hardcoded owner. The list comes from the repo variable
  `GENTAR_NIGHTLY_SUBJECTS` (`owner/repo[:full]`, `:full` meaning clone
  with history and tags); unset means a subjectless run, which is the
  right default for a fork that has named no subjects.
- That variable reaches the job through step `env` rather than `${{ }}`
  interpolation, so its value cannot reach the shell parser.
- The adoption kit's default engine pin moves to `v0.1.1`.

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
