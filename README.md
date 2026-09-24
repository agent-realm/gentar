# gentar

**aGENT ARena** — a standalone end-to-end test runner, reviver, and pilot
simulator.

You point gentar at software a person installs and uses. It brings up a
disposable machine, puts the software through the path a real user would
take — including, when the scenario asks for it, a real AI coding agent
typing at a terminal — and decides pass or fail from what is actually on
that machine afterwards: files, exit codes, processes, SQL rows, spans.
Never from what the software or the agent claims.

**Adapting gentar into a repo?** gentar is not installed into a repo — the
repo becomes a *subject* and the engine stays external and pinned. Agents:
read [`AGENTS.md`](AGENTS.md) first. Humans:
[`subject-template/README.md`](subject-template/README.md).

Three things it does, and the rest of this page in that order:

| Pillar | What it means |
|---|---|
| **End-to-end test runner** | one `docker-compose.yml`, disposable benches, declarative TOML suites, exit code = verdict |
| **Reviver** | every run writes a report that states what happened well enough to fix it — hand it to an agent, the loop closes |
| **Pilot simulator** | a real agent driven at a pty through onboarding dialogs and tasks, as a human pilot would be |

It runs anywhere Docker runs: a laptop, a CI runner, a server.

---

## 1. End-to-end test runner

One compose file carries the whole arena — coordinator, ClickHouse,
otelcol, dashboard. A **bench** (the disposable machine under test) is
not a compose service: the coordinator mints one per run on a
**bench-host** and destroys it afterwards, so a wedged environment is
discarded rather than repaired.

A **scenario** is one TOML file. It declares the subject, the bench, the
reference path to run, and the assertions that must hold against reality
— never a test script in a programming language, and never a shell
harness you have to maintain:

```toml
[scenario]
name = "claude-playbooks-install"
subject = "kommander-playbook"
agent = "shell"

[oracle]
steps = [
  "curl -fsSL https://.../install.sh | VERSION=v3.2.0 sh",
  "claude-playbook install \"$WORKSPACE_DIR\" --name kommander",
]

[[verify.files]]
path = "~/.claude-playbooks/kommander/CLAUDE.md"

[[verify.commands]]
command = "claude-playbook --version"
contains = "v3."
```

That is a real suite — `coordinator/scenarios/claude-playbooks-install.toml`
— and it is the shape of every one of them: the documented install path
verbatim, then nine assertions read back out of the bench (five files, four
commands). If the project's README and the project's reality diverge, this
suite goes red and names the divergence.

**Exit code is the verdict**, and it is the whole contract:

| Code | Meaning |
|---|---|
| `0` | pass |
| `1` | fail — an assertion saw something reality did not support |
| `2` | refusal — a usage or configuration error (unknown scenario, missing credential, over-budget run). Refused *before* any bench exists, so nothing was spent |

Nothing sits between a suite and CI: no test-report format to parse, no
plugin to install. Every step also lands as an OTel span in ClickHouse, and
`docker compose run --rm dashboard` renders a self-contained HTML page of
verdicts with span drill-down.

### Quickstart

Prereqs: a Docker host for the arena, and a **bench-host** — any Linux
machine with the [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)
CLI (`sbx`) installed and logged in once (`sbx login`, device flow; the
token persists).

```bash
cp .env.example .env          # point it at YOUR bench-host + SSH key
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
bin/arena run smoke           # exit code = verdict
ls out/                       # report-<run_id>.md per run
bin/arena sql "SELECT span_name, status FROM gentar.spans ORDER BY ts"
```

gentar ships **no bench-host of its own**, so the variables identifying
yours have no built-in default. If the tier a run selects is
unconfigured, the coordinator refuses with exit 2 before creating any
bench and names the variable it needs — a missing setting never
masquerades as a failing test, and never silently runs somewhere you did
not choose. `.env.example` is a commented template; every value in it is
a placeholder.

```bash
bin/arena run smoke smoke-fail   # several suites, worst verdict wins
bin/arena ls                     # list scenarios
bin/arena dashboard              # render dashboard/out/dashboard.html
bin/arena down                   # tear this project's arena down
bin/arena gc                     # list arenas stranded by older runs
bin/arena gc --yes               # …and remove them (never touches a running one)
```

### Run through `bin/arena`, not bare compose

The documented compose contract is
`docker compose run --rm coordinator run smoke`, and it still works
exactly as CI uses it. But `--rm` removes only the coordinator:
`clickhouse` and `otelcol` start via `depends_on` as ordinary `up`
containers (`AutoRemove=false`) and survive it, and `clickhouse` owns a
named volume — so every distinct compose project strands two containers
and a volume. One machine accumulated thirteen stranded stacks that way.
CI compensates with an `if: always()` teardown step. `bin/arena` gives
two independent structural guarantees instead:

- **Every container is `--rm`.** The compose spec has no per-service
  auto-remove key and `compose up` has no `--rm`, so the wrapper starts
  every service as a one-off `compose run -d --rm` — the only way to get
  daemon-level `AutoRemove`. A stopped arena container is then removed by
  the Docker daemon itself, whatever stopped it: ctrl-c, `SIGKILL`, OOM,
  or the script dying before its trap can run. `compose.rm.yml` turns
  `clickhouse`'s named volume anonymous so `--rm` reclaims that too.
- **A trap tears the project down anyway**, on a pass, a failing verdict,
  a refusal and a ctrl-c alike — covering the network, and anything a
  future edit starts the ordinary way.

Keep a stack up to poke at ClickHouse with `GENTAR_KEEP_ARENA=1`, then
`bin/arena down`. While it is up, `python3 dashboard/generate.py --watch`
renders a self-refreshing dashboard from it to `dashboard/out/dashboard.html`
(it follows `GENTAR_CLICKHOUSE_HOST_PORT` if you moved the port). Arena ClickHouse data does not survive a teardown; it
never did — every teardown path runs `down -v`.

### Bench tiers

Four backends behind one interface (`coordinator/gentar/benchhost.py`).
A scenario opts in with `bench = "<tier>"`; the install default is
`GENTAR_BENCH_KIND` (`sbx`).

| Tier | Bench is | Reached by | Substrate proof |
|---|---|---|---|
| `sbx` (default) | a Docker Sandboxes microVM — own kernel, own Docker daemon | SSH to the bench-host, then `sbx create/exec/rm` | `smoke` |
| `tart` | a macOS VM cloned from a local template, on Apple hardware | `ssh` through the Mac running the tart CLI | `smoke-macos` |
| `osb` | a plain Linux container (any image) | HTTP + WebSocket to an [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) server — no SSH at all | `smoke-osb` |
| `daytona` | a [Daytona](https://www.daytona.io) cloud sandbox | `ssh` to Daytona's gateway with a per-sandbox expiring token as the username | `smoke-daytona` |

The microVM tier is the default because each bench gets its own Docker
daemon: a scenario can let the software under test start containers, and
they are born inside the bench, provably not on the host. `memhouse-house`
uses exactly that — it stands up a real ClickHouse inside the bench.

Only the `sbx` tier is in the CI gate; the other three need hardware or
an account the gate runner does not have. Their setup is in
[the tier notes](#bench-tier-setup) at the bottom.

---

## 2. Reviver

A test runner that only says "fail" makes a human go read logs. gentar
writes, on **every** terminal outcome — pass, fail, and refusal alike —
a markdown report at `out/report-<run_id>.md`
(`coordinator/gentar/report.py`). It contains:

- a header table: run id, verdict and exit code, subject, bench agent and
  template, the credential **names** the run required, sandbox, timestamps;
- **a reproduce command** — the exact invocation that re-runs this suite;
- **every step**, in order, with its exit code and a tail of its output;
- **every assertion**, pass or fail, with what it checked and what it
  actually saw;
- **the pty transcript** when a driver ran — the evidence behind an
  agent-in-the-loop verdict;
- the summary line.

That file is the deliverable of a failing run. Feed it to a coding agent
and it has everything it needs to act: what ran, what it printed, which
assertion disagreed with reality, and how to run it again. Feed it to a
human and they skip the log archaeology. The fix loop closes without
anyone re-deriving the failure.

Try it in one command. `smoke-fail` is the built-in sabotage probe — it
runs a bench command that exits 3, on purpose, to prove the verdict
machinery detects failure at all:

```bash
bin/arena run smoke-fail      # exits 1
cat out/report-*.md
```

Two rules make the reports safe to pass around:

- **Names, never values.** A run report and a span carry the *names* of
  the environment variables a run required. A credential value must never
  reach a report, a span, or a log line.
- **A report never changes a verdict.** Writing it is best-effort in a
  `finally` block; a report that fails to write warns and the exit code
  stands.

Reports are also what the adoption kit wires by default — a subject's own
arena lands them in its repo under `gentar/reports/`.

---

## 3. Pilot simulator

Most testing drives software through its API. A pilot simulator drives it
through its **terminal**, as the person would: a real agent CLI at a real
pty on the bench, answering its onboarding dialogs, typing a task,
waiting for the reply.

A scenario's `[driver]` block names the command and a list of **turns**
(`coordinator/gentar/scripted.py`):

| Turn | Does |
|---|---|
| `answer` | wait for a prompt pattern, then type text |
| `expect` | wait for a pattern to appear on screen |
| `pick` | walk a `❯`-cursor picker to a labeled option and select it |
| `key` | send raw key events (`enter`, `escape`, `ctrl-c`), optionally anchored to a screen and paced |
| `abort` | prove the danger gate fires |

`agent-pty-smoke` is the live suite: a real `claude-code` TUI on a bench,
driven through its entire first run — theme picker, declining the
sandbox's inert placeholder API key, the confirm footer, an intermittent
security-notes page, the trust-folder dialog, the bypass-permissions
warning — then given a task, then exited. The verdict is a byte-for-byte
`cmp` of the file it was asked to write. Not the agent's reply. Not the
transcript. The file.

Three mechanics the driver had to learn, all proven live on a bench and
all encoded in the turn schema, because they are the difference between a
script that works and one that is subtly lying:

- **Submission is a separate event.** The TUI paste-guards a trailing
  Enter that arrives in the same write as the text, so every `answer` into
  an input box is followed by its own `key enter` turn — and it must be a
  real `\r`; a `sendline`'s `\n` is ignored.
- **The screen is a diff, not a stream.** The TUI re-sends only changed
  cells and jumps the cursor across unchanged ones, so a single frame
  literally lacks letters still on screen. The driver replays the pty
  stream through a cell model (`_render` in
  `coordinator/gentar/pty_driver.py`, unit-tested in
  `coordinator/tests/test_render.py`) instead of tailing raw bytes.
- **Turns are anchored, not blind.** An Enter waits for its own screen
  (`after = "…"`), because a paced pair races the render and can
  pre-accept the *next* dialog's default. A dialog that appears only
  sometimes is an `optional` turn.

The hard safety rule in the driver is the **danger gate**: if the agent
provokes a prompt asking to run a command matching the destructive-command
pattern, the driver aborts the run rather than approving it. That is not a
documented intention — `scripted-danger` is a gate suite that fails unless
the gate fires before any approval, and it runs on every PR.

**Credentials are injected at run time and never baked.** A scenario
declares the environment variable *names* it needs. Entries are
alternatives, and a list entry is an all-of group:

```toml
credentials = ["ANTHROPIC_API_KEY",
               ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]]
```

The first fully-present group wins and is forwarded whole; nothing outside
it travels, so a stray endpoint variable cannot redirect a key that won on
its own. If no group is complete, the run **refuses with exit 2 before any
bench exists** — a missing credential is a usage error, not a red test, and
a token without its endpoint is half a provider, which never gets to start
a misconfigured bench. Any Anthropic-protocol endpoint works, not just the
first-party one.

The value has to reach the *coordinator* first, and a container inherits
nothing from your shell: `bin/arena` reads the names each scenario
declares and passes them through with `-e NAME`, so exporting them is
enough. Bare `docker compose run` does not — add the same `-e` flags, as
the CI contract above does.

Today the agent under the pty is `claude-code`, pinned by
`bench-template/VERSION` and baked into the bench template so no run
depends on a registry at test time. The driver itself is agent-agnostic;
adding another CLI is a turn script, not engine work.

---

## History — runs that outlive their stack

An arena's ClickHouse dies with the arena. The **history store** is one
persistent ClickHouse on the arena host (`history/`) that every run can ALSO
write to, so runs, suites and subjects can be compared over time: pass rate
per suite, median durations, and the agent's numbers — tokens, turns, tool
calls — taken from its session transcript.

What reaches it is decided before a row leaves the coordinator:

- the bench-host settings and every credential a suite declares are
  scrubbed, in every encoding and any 8+ character prefix;
- an agent's transcript is never stored — only numbers derived from it,
  with tool names reduced to Claude Code's built-ins, `mcp` or `other`;
- three identities: an admin for the schema, a **writer** that can only
  insert, a **reader** that can only select. Bound to `127.0.0.1` on the
  host; arenas reach it over the `gentar-history` docker network.

The identities guard the network edge; they do not keep out code that runs
on the arena host itself (CI runners there share the user and the docker
group). That boundary is the run policy's: only trusted code reaches the
self-hosted runner — the same trust the bench SSH key already relies on.

```bash
bin/history deploy                  # on the arena host: passwords generated there, never shown
bin/history writer-secret owner/repo # a repo's CI may write (piped into its Actions secret)
bin/history reader-keychain         # this Mac may read (keychain:pilot/gentar-history-reader)
bin/history tunnel &                # 127.0.0.1:18199 -> the host
with-secret GENTAR_HISTORY_READER_PASSWORD=keychain:pilot/gentar-history-reader \
  -- bin/history dashboard          # dashboard/out/history.html, with trends
```

A repo turns it on with two variables — `GENTAR_HISTORY_URL=http://gentar-history:8123`,
`GENTAR_HISTORY_NETWORK=gentar-history` — and the secret
`GENTAR_HISTORY_WRITER_PASSWORD`. Unset, nothing is written; a failed write
never changes a verdict.

## Scenario inventory

22 suites: 20 TOML files in `coordinator/scenarios/`, plus two Python
built-ins (`smoke`, `smoke-fail`). Every verdict comes from reality.
List them live with `bin/arena ls`.

Where a suite names another project, this is what it is: **kommander-playbook**
is a Claude Code configuration playbook, **memhouse** is a ClickHouse-backed
memory service, **claude-playbooks** is the CLI that installs playbooks.

| Suite | Tier | What it proves |
|---|---|---|
| `smoke` | sbx | bench lifecycle: create → exec `uname -a` → span → destroy |
| `smoke-fail` | sbx | the verdict machinery itself: a sabotaged step must produce exit 1 and still tear the bench down |
| `smoke-macos` | tart | Darwin arm64 + the pinned CLI on a Mac bench |
| `smoke-osb` | osb | Linux container bench driven entirely over the OpenSandbox API |
| `smoke-daytona` | daytona | cloud sandbox minted via SDK, driven over ssh with an expiring token |
| `bench-template-verify` | sbx | a bench from `gentar-bench-v1` carries the pinned agent CLI |
| `otlp-selfreport` | sbx | software inside the bench can self-report OTLP spans that join harness spans on `run_id` in one SQL |
| `budget-sim` | sbx | the budget guard refuses an over-cap run (exit 2) |
| `scripted-onboarding` | sbx | pty driver mechanics: answer / pick / expect turns, no LLM |
| `scripted-danger` | sbx | the danger gate fires before any approval |
| `agent-smoke` | sbx | a real `claude-code` does a trivial task headlessly; provider-agnostic credential, refuses without one |
| `agent-pty-smoke` | sbx | **pilot simulation**: a real `claude-code` TUI driven through first-run onboarding and a task; byte-exact file verdict |
| `agent-profile-smoke` | sbx | a real agent running *under* a configuration install pinned to the newest release tag — the ref under test is never its own tool; triple reality verdict |
| `claude-playbooks-install` | sbx | the documented CLI install path, verbatim, 9 reality assertions |
| `claude-playbooks-install-macos` | tart | the same suite on a Mac bench — installers behave identically on darwin/arm64 |
| `kommander-install` | sbx | the README's standalone install path: in-place install, launcher, data dirs, helper |
| `kommander-update` | sbx | upgrade from an old release tag to the checkout's VERSION; data survives `reset --hard` |
| `kommander-task-lock` | sbx | a lock guard's exit contract under a live PID matrix (0 acquired / 2 live / 3 stale) |
| `memhouse-install` | sbx | `npm install -g` from the mounted checkout; schema claims read out of the shipped artifacts |
| `memhouse-house` | sbx | a real service deployed inside the bench's own Docker daemon; verdicts are SQL counts against it |
| `docs-honesty-kommander` | sbx | a README's install *and* uninstall paths run verbatim, drift-guarded |
| `docs-honesty-gentar` | sbx | this README's own claims, checked against this repo |

The last one is worth a sentence. `docs-honesty-gentar` greps this file
for the commands it tells you to run, then proves their targets exist:
`.env.example`, `docker-compose.yml`, `dashboard/generate.py`,
`bench-template/VERSION`, the scenarios named above, the CI job names.
If this README drifts from the repo, the release gate goes red. Docs
honesty is a dimension under test, not an aspiration.

---

## CI contract

`docker compose up` plus an exit code is the entire integration surface —
no forge-specific features inside the arena, so the same suites run on
GitHub, Gitea, Jenkins, cron, or a laptop unchanged. The GitHub wiring
that exists today ([`.github/workflows/gentar.yml`](.github/workflows/gentar.yml)):

| Tier | Fires on | Runs |
|---|---|---|
| gate | every PR, every push to `main` | six deterministic bench-only suites: `smoke`, `bench-template-verify`, `otlp-selfreport`, `budget-sim`, `scripted-onboarding`, `scripted-danger` |
| keyword tag | a tag pushed at **any** commit | `arena` → every gate suite at that commit, unmerged branches included; `arena-<scenario>` → that one suite (an unknown name refuses with exit 2, no bench spent); `v*` → **release proof**, the full gate. Re-run by deleting and re-pushing the tag |
| nightly | cron, post-merge | the scripted and real-agent suites plus every subject suite, behind a budget cap and a read token |
| dispatch | manual, or from another repo | one named scenario at an arbitrary engine ref and subject ref |

The gate runs one bench at a time on purpose: concurrent `sbx create`
calls on a shared bench-host contend on a cross-process auth lock and
wedge each other.

Two coordinator-side guards keep a scheduled arena from running away:
a **budget guard** (`GENTAR_BUDGET_CAP` against each scenario's declared
`[budget] tokens`, accumulated from past runs' spans) that refuses an
over-cap run with exit 2, and a **flake quarantine**
(`GENTAR_QUARANTINE=name,…`) that skips a named suite rather than failing
it. Both live in the engine, not in forge features, so they survive a
change of forge.

---

## Releases

`VERSION` at the repo root is the engine version; `CHANGELOG.md` records
what each one contains.

Cutting a release:

1. Bump `VERSION`.
2. Add the `CHANGELOG.md` entry.
3. Tag `v$(cat VERSION)` and push the tag.

The tag *is* the proof. A `v*` tag runs the full gate at that commit, and
a guard in the workflow fails the job if the tag does not equal
`v$(cat VERSION)` — so a release tag can never disagree with the file it
claims to be.

**What an adopter pins** is a git ref of this repo (`GENTAR_REF` in the
adoption kit). Pin a release tag, not a branch: scenario TOML schema and
the exit-code contract are stable within a minor version, engine internals
are not. Pre-1.0, a minor bump may change the schema — read the changelog
before moving.

---

## Adopting gentar in your repo

Three moves: **copy the kit, own your scenarios, pin the engine version.**

- [`subject-template/`](subject-template/) is the copyable kit — a
  `gentar/` directory with a commented scenario, a runner, a bench-less
  dry-run replay, and a workflow.
- [`docs/subject-integration.md`](docs/subject-integration.md) is the
  full contract: the two trigger modes (run your own arena, or dispatch
  to a central one), credentials, and conventions.

The one rule worth stating here, because it is what the arena exists to
enforce: **subjects mount, never bake.** Your checkout is staged into the
run at run time and delivered into a fresh bench. No image ever carries
it, so there is no sandbox image to rebuild and no stale copy to test by
accident.

---

## License

MIT — see [LICENSE](LICENSE). The repository is private today; the
license is the terms under which it is shared, not a statement about
who can reach it.

## Scope map

New to the vocabulary, or unsure which machine holds what?
**[`docs/scope-map.md`](docs/scope-map.md)** — what contains what, every
relation counted (`1 → 1`, `1 → N`, `N → 1`, `N → M`), and the three
cardinalities people get backwards: a runner is not per-run, a job is not
per-scenario, and a second runner does not give you a second bench-host.
A rendered version with hand-drawn figures sits beside it at
[`docs/scope-map.html`](docs/scope-map.html).

## Design tenets

- **Verdicts from reality.** Files, exit codes, processes, SQL, spans,
  screen contents. Never "the software said it worked", and never "the
  agent said it worked". Self-reported telemetry is welcome — it joins
  harness spans on `run_id` — but it is evidence, not a verdict.
- **The bench is the reset.** Every scenario gets a fresh one, and a
  wedged run is discarded rather than repaired.
- **Subjects mount, never bake.** See above.
- **Refuse, don't fail.** A missing credential, an unknown suite name, an
  over-budget run: these are usage errors. They exit 2 before a bench is
  created, so a misconfiguration costs nothing and never masquerades as a
  broken product.
- **Names, never values.** Credentials travel as environment variables
  into a throwaway that dies with the run. Spans and reports carry the
  names a run required.
- **Machinery is pinned, never itself.** When a suite's own tooling
  overlaps the thing under test, the tooling is pinned to a previous
  release. The ref under test is never its own test harness.
- **Nothing between a suite and CI.** `docker compose run` and an exit
  code. No report format, no plugin, no forge feature in the critical
  path.

gentar was born in the [Ultimagent](https://github.com/agent-realm/ultimagent)
constellation, whose components are its first adopters; nothing in the
engine depends on that, and the suites above that name other projects are
simply the subjects it was proven against.

---

## Bench tier setup

The default `sbx` tier needs only the Quickstart. The other three need
something the CI gate runner does not have, so they are documented rather
than gated.

### `tart` — macOS benches

Benches are clones of a local template VM (`gentar-bench-macos-v1`:
sshd on, the coordinator's public key authorized, agent CLIs on PATH via
the guest's `~/.zshenv`). The Mac runs the tart CLI; guests are reached by
ssh *through* that Mac, because the guest's vmnet subnet is routed only
there. So the coordinator must run somewhere with a route to the Mac —
typically a container on the Mac itself.

```bash
docker build -t gentar-coordinator coordinator/
docker run --rm \
  -v "$HOME/.ssh/id_ed25519:/run/secrets/bench_ssh_key:ro" -v "$PWD/out:/out" \
  -e GENTAR_TART_HOST=host.docker.internal \
  -e GENTAR_BENCH_KEY=/run/secrets/bench_ssh_key \
  -e GENTAR_BENCH_KNOWN_HOSTS=/dev/null \
  gentar-coordinator run smoke-macos
```

Subject suites on this tier need the subject mounted at the coordinator's
subjects root, e.g. `-v <path-to-subject>:/subjects/<name>:ro`. Template
rebuilds are manual: boot the template VM, provision it, `tart stop`.

### `osb` — OpenSandbox containers

Benches are plain Linux containers under an OpenSandbox server: `create`
maps to a sandbox, `exec` to the execd command API (real exit codes),
`push_dir` to a tarball through the files API, and the pty driver reaches
execd's PTY WebSocket through a small local bridge
(`coordinator/gentar/osb_pty_bridge.py`). No SSH anywhere. The server ships
as an optional compose profile:

```bash
docker compose --profile osb up -d osb-server
docker compose --profile osb run --rm \
  -e GENTAR_BENCH_KIND=osb -e GENTAR_OSB_SERVER=http://osb-server:8080 \
  coordinator run smoke-osb
```

Templates are image refs on the server's Docker daemon
(`GENTAR_OSB_TEMPLATE`, default `python:3.12-slim`). An external server
works too — point `GENTAR_OSB_SERVER` at it.

### `daytona` — cloud sandboxes

`create` mints a sandbox from a public image ref through the Daytona SDK;
`exec` and the pty driver go over ssh to Daytona's fixed gateway with a
per-sandbox expiring token as the username — no key file. `push_dir`
streams a tarball over that same session. No infrastructure of your own in
the bench path; it costs Daytona credits per sandbox-hour.

```bash
docker compose run --rm \
  -e GENTAR_DAYTONA_API_KEY="$DAYTONA_API_KEY" \
  coordinator run smoke-daytona
```

Images need a tag or digest — Daytona rejects `latest`. The API key is
**coordinator-scoped and never a scenario credential**: declared
credential values travel into the bench, and the key that mints sandboxes
must not live inside one. The ssh tokens expire by design, so a leaked one
is short-lived.

---

## Layout

| Path | What |
|---|---|
| `docker-compose.yml` | the arena: coordinator, ClickHouse, otelcol, dashboard |
| `bin/arena` | the local entry point, and the one that cannot leak |
| `coordinator/gentar/` | the engine — bench tiers, oracle runner, pty driver, assertions, spans, reports |
| `coordinator/scenarios/` | the suites |
| `bench-template/` | deterministic bench template builder; `VERSION` pins the agent CLI |
| `dashboard/generate.py` | stateless HTML renderer over the spans table (`--history`: trends) |
| `history/`, `bin/history` | the persistent history store and its operator tool |
| `bin/redact`, `bin/bench-reap` | publish-time redaction; stranded-sandbox cleanup |
| `subject-template/` | the copyable adoption kit |
| `docs/design.md` | the design of record, with every decision and why |
| `docs/subject-integration.md` | the adoption contract |
