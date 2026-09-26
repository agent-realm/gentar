# End-to-end test runner

How gentar runs a suite: the compose stack, disposable benches, declarative TOML suites, and the exit code as the verdict.

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

## Quickstart

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

## Run through `bin/arena`, not bare compose

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

## Bench tiers

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
[the tier notes](bench-tiers.md) at the bottom.
