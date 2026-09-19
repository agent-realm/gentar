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
| `bench ×N` | **sbx sandboxes** (Docker Sandboxes) spawned by the coordinator on a bench-host — per-run microVM, own Docker daemon each; macOS tier: tart VMs; container tier: OpenSandbox; cloud tier: Daytona sandboxes |
| `telemetry` | ClickHouse + otelcol-contrib; spans schema ported from agent-gauntlet |
| `dashboard` | stateless verdicts + span drill-down |

Benches are not compose services. The compose file carries coordinator +
telemetry (+ dashboard); the coordinator creates and destroys each bench
over SSH (`sbx create/exec/rm` on Linux, `ssh` for tart macOS VMs),
through the OpenSandbox server's API (container tier), or through the
Daytona SDK + its ssh gateway (cloud tier).

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
| PR gate | every PR / push to main | 6 deterministic subjectless suites (matrix in [.github/workflows/gentar.yml](.github/workflows/gentar.yml)); exit code is the verdict |
| keyword tags | tag pushed at ANY commit | `arena` → every gate suite at that commit (unmerged branches included); `arena-<scenario>` → that one suite (unknown name → exit-2 refusal, no bench spent); `v*` → release proof = every gate suite. Re-run: delete and re-push the tag |
| nightly | post-merge, cron 00:17 | `scripted-onboarding`, `agent-smoke`, `agent-profile-smoke` (when an agent credential is set — `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN`+`ANTHROPIC_BASE_URL` for any Anthropic-compatible endpoint, e.g. the GLM coding plan; optional cheaper-model pin via the `ANTHROPIC_DEFAULT_SONNET_MODEL` repo var, e.g. `glm-5.3-flash`) + all subject suites, behind `GENTAR_SUBJECT_TOKEN` and the budget guard |
| dispatch | manual / from a subject repo | one named scenario, arbitrary gentar ref + subject ref (see [docs/subject-integration.md](docs/subject-integration.md)) |

## Scenario inventory

19 suites today — every verdict from reality; two (`agent-smoke`,
`agent-profile-smoke`) put a real claude-code in the loop, behind a
declared credential.
(`coordinator ls` also lists `smoke-fail`, the built-in sabotage probe
that proves failure detection itself.)

| Suite | Subject | What it proves |
|---|---|---|
| `smoke` | — | bench lifecycle: create → exec `uname -a` → span → destroy |
| `smoke-macos` | — | tart tier substrate proof: Darwin arm64 + pinned CLI on a Mac bench (not in the CI gate; see macOS tier) |
| `smoke-osb` | — | osb tier substrate proof: Linux container bench on the OpenSandbox server (not in the CI gate; see osb tier) |
| `smoke-daytona` | — | daytona tier substrate proof: Linux cloud sandbox minted via the Daytona SDK, driven over ssh with an expiring token (not in the CI gate; see daytona tier) |
| `bench-template-verify` | — | benches from `gentar-bench-v1` carry the pinned claude-code |
| `otlp-selfreport` | — | agent self-report: OTLP drop-file relay joins harness spans in one SQL |
| `budget-sim` | — | budget guard refuses over-cap runs (exit 2) |
| `scripted-onboarding` | — | pty driver: answer / pick / confirm / expect turns |
| `scripted-danger` | — | danger gate fires before any approval |
| `agent-smoke` | — | real claude-code (bench template) does a trivial task headlessly; provider-agnostic credential (`ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN`+`ANTHROPIC_BASE_URL` — any Anthropic-compatible endpoint, GLM coding plan proven), refuses without any; optional `ANTHROPIC_DEFAULT_SONNET_MODEL` pin (e.g. `glm-5.3-flash`) rides `pass_env`, no guard |
| `agent-profile-smoke` | kommander-playbook | real claude-code runs UNDER a playbook install pinned to the newest release tag (anti-ouroboros: the ref under test is never its own tool); verdict = version.txt equals the pinned machinery's VERSION — task done AND run under the pin |
| `claude-playbooks-install` | kommander-playbook | documented `claude-playbook` CLI install path, 9 reality assertions |
| `claude-playbooks-install-macos` | kommander-playbook | the same suite on a tart Mac bench — installers and launchers behave identically on darwin/arm64 |
| `kommander-install` | kommander-playbook | README standalone path: in-place install, alias, data dirs, helper |
| `kommander-update` | kommander-playbook | upgrade: v3.4.0 → subject VERSION; data survives `reset --hard` |
| `kommander-task-lock` | kommander-playbook | lock guard exit contract (0 acquired / 2 live / 3 stale) |
| `memhouse-install` | memhouse | `npm install -g` from the checkout; schema claims via `install --print-sql` |
| `memhouse-house` | memhouse | real `deploy --local` house in the bench; sql-count verdicts |
| `docs-honesty-kommander` | kommander-playbook | README install + uninstall paths verbatim, drift-guarded |
| `docs-honesty-gentar` | gentar itself | this README's own claims (quickstart targets, named suites, tiers) |

List them live: `docker compose run --rm coordinator ls`.

## Integrating your repo (becoming a subject)

Full contract: [docs/subject-integration.md](docs/subject-integration.md).
The short version — three moves, two of them in your repo:

1. **State your scenarios as decisions, not steps.** A TOML per suite:
   what to install, what reality to assert. Either carry them in your
   repo under `gentar/`, or PR them into `coordinator/scenarios/`
   (how every current subject suite lives).
2. **Add the ~10-line trigger job** to your repo (`.github/workflows/gentar.yml`)
   that fires `workflow_dispatch` on `agent-realm/gentar` with the
   scenario name and your PR head sha as `subject_ref` — the arena then
   tests exactly the code under review. Needs `GENTAR_DISPATCH_TOKEN`
   (PAT, `actions:write` on gentar) as a secret in your repo.
3. **Nothing else on your side.** The arena clones your checkout itself
   (needs `GENTAR_SUBJECT_TOKEN`, a `repo:read` PAT, as a gentar
   secret), mounts it into the coordinator, and verdicts land in the
   dashboard. No sandbox images, no baked checkouts — subjects mount,
   arenas run.

Kommander-playbook is the reference subject: its suites run
`claude-playbooks-install`, `kommander-install`/`-update`/`-task-lock`,
and `docs-honesty-kommander` from the same trigger.

## Status

Design of record ([docs/design.md](docs/design.md)) and build plan
([docs/buildplan-2026-08-18-v1.md](docs/buildplan-2026-08-18-v1.md))
landed. **Phases 0–7 done — build plan v1 is exhausted.** What exists,
all merged to main and gate-verified per PR:

- **Arena skeleton** — one compose file: coordinator + ClickHouse +
  otelcol (+ dashboard); benches = sbx sandboxes spawned over SSH on a
  bench-host.
- **TOML scenarios + oracle runner** — declarative suites, no LLM,
  assertions from files / commands / SQL.
- **pty driver** — pexpect over `ssh -tt … sbx exec -t`; gauntlet
  policies ported (approval auto-approve, danger gate, picker
  navigation by ❯ cursor line); exercised by the scripted pair.
- **Bench templates** — `bench-template/build.sh` builds a
  deterministic template on the bench-host (claude-code pinned by
  `bench-template/VERSION`); the bench.create span records template
  tag + image digest.
- **Telemetry + dashboard + guards** — gauntlet spans schema ported
  (subject-leading sort, two-row scenario spans,
  `latest_scenario_status` view, 14 provenance attrs); agent
  self-report: benches drop OTLP-JSON at
  `$WORKSPACE_DIR/gentar-otlp.json`, the coordinator relays it to
  otelcol, and **one SQL joins harness spans with agent OTLP** on the
  `gentar.run_id` resource attribute; the dashboard renders via
  `docker compose run --rm dashboard`; budget guard
  (`GENTAR_BUDGET_CAP` + `[budget] tokens`) refuses over-cap runs with
  exit 2; flake quarantine (`GENTAR_QUARANTINE=…`) skips, never fails.
- **CI** — three tiers on the self-hosted `gentar-bench` runner (see
  the CI contract table above).
- **Subjects onboarded (phase 7)** — kommander-playbook (install /
  update / task-lock), memhouse (install / real house), docs-honesty
  v1 for both kommander-playbook and gentar itself — the quickstart's
  `.env.example` exists because `docs-honesty-gentar` demanded it.
- **macOS tier (tart)** — a second BenchHost implementation: tart VMs
  cloned from a local template (`gentar-bench-macos-v1`, claude-code
  pinned) on an Apple-Silicon Mac, driven headless over ssh through the
  tart host. A scenario opts in with `bench = "tart"`; `smoke-macos`
  is the substrate proof (Darwin arm64 + pinned CLI) and
  `claude-playbooks-install-macos` is the first subject suite on the
  tier — the documented installer path behaves identically on
  darwin/arm64. Not part of the CI gate — the gate runner is Linux
  with no route to the Mac; run these where the Mac is reachable (see
  the macOS tier section below).
- **Container tier (OpenSandbox)** — a third BenchHost implementation:
  benches are plain Linux containers (any image, e.g. `python:3.12-slim`)
  driven through an [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox)
  server — no SSH involved; exec, file push, and pty all go through the
  server's per-sandbox execd daemon. The server ships as an optional
  compose profile (`--profile osb`, config in `osb/server.toml`); a
  scenario opts in with `bench = "osb"`, and `smoke-osb` is the substrate
  proof. Not part of the CI gate — the runner hosts no osb server (see
  the osb tier section below).
- **Cloud tier (Daytona)** — a fourth BenchHost implementation: benches
  are Linux cloud sandboxes minted through the [Daytona](https://www.daytona.io)
  SDK from a public image ref, driven by ssh against Daytona's fixed
  gateway with a per-sandbox **expiring token as the username** — the
  same ssh shape as the tart tier minus the key file. No infra of your
  own anywhere in the bench path. A scenario opts in with
  `bench = "daytona"`, and `smoke-daytona` is the substrate proof.
  Not part of the CI gate — the runner would need the Daytona API key
  (see the daytona tier section below).

**Not built yet** (deliberate, not forgotten): interactive real-agent
runs — claude-code driven through the pty driver's turns inside a
bench (headless agent-smoke is live; see the scenario inventory).
Also deferred from plan v1:
Forgejo/Gitea forge swap, `--kit` evaluation, multi-bench parallel
matrices.

## Quickstart

Prereqs: a Docker host for the arena, and a **bench-host** — any Linux
machine with `sbx` installed and logged in once (`sbx login`, device
flow; the token persists).

```bash
cp .env.example .env          # point at your bench-host + SSH key
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
docker compose run --rm coordinator run smoke   # exit code = verdict
ls out/   # report-<run_id>.md per run — failure reports are agent-feedable
docker compose exec clickhouse clickhouse-client \
  --user gentar --password gentar \
  -q "SELECT span_name, status FROM gentar.spans ORDER BY ts"
```

Defaults in `.env.example` point at the current bench-host — the VM on
arf (`10.10.10.52`, VM 142 `gentar-bench-host`) the runner lives on.

### macOS tier (tart)

The tart tier runs on the pilot's Mac (`macminim`): template VM
`gentar-bench-macos-v1` (claude-code pinned by
`bench-template/VERSION`, coordinator key authorized, agent CLIs on
PATH via the guest's `~/.zshenv`). The Mac runs the tart CLI; benches
are per-run clones, reached by ssh through the tart host (the guest's
vmnet subnet is only routed on the Mac — so the coordinator must run
somewhere with a route to the Mac, typically a container on the Mac
itself with `GENTAR_TART_HOST=host.docker.internal`).

```bash
# from a checkout on the Mac, against a local Docker (OrbStack works):
docker build -t gentar-coordinator coordinator/
docker run --rm \
  -v "$HOME/.ssh/id_ed25519:/run/secrets/bench_ssh_key:ro" -v "$PWD/out:/out" \
  -e GENTAR_TART_HOST=host.docker.internal \
  -e GENTAR_BENCH_KEY=/run/secrets/bench_ssh_key \
  -e GENTAR_BENCH_KNOWN_HOSTS=/dev/null \
  gentar-coordinator run smoke-macos   # exit code = verdict
```

Template rebuild is manual (boot the template VM, provision, `tart
stop`); see the session log 2026-08-28 for the exact bring-up.

Subject suites on the tier (`claude-playbooks-install-macos`) need the
subject mounted at the coordinator's subjects root, e.g. add
`-v <path-to-kommander-playbook>:/subjects/kommander-playbook:ro`.

### osb tier (OpenSandbox)

The osb tier runs benches as plain Linux containers under an
[OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) server:
`create` maps to a sandbox (tagged `gentar.name` in its metadata), `exec`
to the execd command API (real exit codes, per-run env), `push_dir` to a
tarball through the files API, and the pty driver reaches execd's PTY
WebSocket through a small local bridge (`coordinator/gentar/osb_pty_bridge.py`).
No SSH anywhere — the coordinator talks HTTP/WebSocket to the server,
which spawns sibling containers on its Docker host.

The server itself is an optional compose profile (official
`opensandbox/server` image, config in `osb/server.toml`, state in the
`osb-data` volume):

```bash
docker compose --profile osb up -d osb-server
docker compose --profile osb run --rm \
  -e GENTAR_BENCH_KIND=osb -e GENTAR_OSB_SERVER=http://osb-server:8080 \
  coordinator run smoke-osb   # exit code = verdict
```

Any scenario runs on the tier by env flip (`GENTAR_BENCH_KIND=osb`) or
per-scenario `bench = "osb"`; templates are image refs on the server's
Docker daemon (`GENTAR_OSB_TEMPLATE`, default `python:3.12-slim`). An
external server works too — point `GENTAR_OSB_SERVER` at it (see
`.env.example`). Not in the CI gate: the runner hosts no osb server.

### daytona tier (Daytona cloud)

The daytona tier runs benches as Linux cloud sandboxes on
[daytona.io](https://www.daytona.io): `create` mints a sandbox from a
public image ref through the Daytona SDK (`daytona` pip package,
`GENTAR_DAYTONA_API_KEY` required), `exec` and the pty driver go over
ssh against Daytona's fixed gateway (`ssh.app.daytona.io`) with a
**per-sandbox expiring token as the username** — `ssh <token>@ssh.app.daytona.io`,
no key file, real exit codes, `ssh -tt` gives a real PTY. `push_dir`
streams a tarball over that same ssh session; `rm` deletes the sandbox
through the SDK. No infra of your own in the bench path — the tier
costs daytona credits per sandbox-hour.

```bash
docker compose run --rm \
  -e GENTAR_DAYTONA_API_KEY="$DAYTONA_API_KEY" \
  coordinator run smoke-daytona   # exit code = verdict
```

Any scenario runs on the tier by env flip
(`GENTAR_BENCH_KIND=daytona`) or per-scenario `bench = "daytona"`;
templates are public image refs with a tag or digest — no `latest`
(Daytona rejects it), default `python:3.12-slim`
(`GENTAR_DAYTONA_IMAGE`). Two security notes that shape the wiring:
the API key is **coordinator-scoped, never a scenario credential** —
declared credential values travel into the bench, and the key that
mints sandboxes must not live inside one (`smoke-daytona.toml` says
so in a comment); and the ssh tokens expire by design (120 min), so a
leaked one is short-lived. Not in the CI gate: the runner has no
Daytona API key to spend.
