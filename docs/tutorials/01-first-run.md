# Tutorial 1 — First run

You will run the engine's built-in `smoke` suite from a checkout of this
repository. It creates a disposable bench on your own bench-host, runs
`uname -a` in it, records a span, and destroys the bench. Then you will
read the verdict, the report and the dashboard.

About 15 minutes, most of it one-time bench-host setup.

## Prerequisites

- **Docker** on the machine you run from: a laptop is fine.
- **A bench-host.** Any Linux machine you can SSH into, with the
  [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) CLI `sbx`
  installed and logged in once (`sbx login`, a device flow; the token
  persists). gentar ships no bench-host of its own.
- **An SSH key** that reaches the bench-host, on the machine you run
  from. It is mounted into the coordinator, never copied into a bench.
- A clone of this repository.

## 1. Point the arena at your bench-host

```bash
cp .env.example .env
$EDITOR .env        # GENTAR_BENCH_HOST, GENTAR_BENCH_USER: YOUR machine and account
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"   # the key that reaches it
```

You should see: `grep -E '^GENTAR_BENCH_(HOST|USER)' .env` names your
machine and account, with no `example` left in either value.

## 2. Run the suite

```bash
bin/arena run smoke
echo "exit: $?"
```

`bin/arena` builds the coordinator image, brings up ClickHouse and the
OTel collector, runs the suite, and tears everything down on every
outcome.

You should see, among the build output:

```
smoke ok: Linux ... (the bench's uname -a)
report: /out/report-<run_id>.md
exit: 0
```

The exit code is the verdict: `0` pass, `1` fail, `2` refusal.

## 3. Read the report

```bash
ls out/                    # report-<run_id>.md, one per run
cat out/report-*.md
```

The report has a header table (run id, verdict, bench, timestamps), a
reproduce command, every step with its output, and the summary line. On
a failure it is the work order: see [Debug a red run](../guides/debug-a-red-run.md).

## 4. See the failure path once

`smoke-fail` is the built-in sabotage probe. It runs a bench command that
exits 3 on purpose, to prove the verdict machinery detects a failure:

```bash
bin/arena run smoke-fail
echo "exit: $?"            # 1
```

## 5. Look inside with the arena kept

A normal run tears the arena down, and its ClickHouse goes with it. To
inspect the spans, keep it up:

```bash
export GENTAR_KEEP_ARENA=1     # every command below keeps the arena up
bin/arena run smoke
bin/arena sql "SELECT step, status, duration_ms FROM gentar.spans ORDER BY ts_start"
bin/arena dashboard        # renders dashboard/out/dashboard.html
open dashboard/out/dashboard.html
bin/arena down             # you own the teardown when you keep the arena
unset GENTAR_KEEP_ARENA
```

You should see: rows for `scenario`, `bench.create`, the step and
`run.end`, and a dashboard page with the run's verdict and its steps.

## When it fails

| You see | Meaning | Fix |
|---|---|---|
| `bench config: sbx benches need GENTAR_BENCH_HOST and GENTAR_BENCH_USER — unset`, exit 2 | the arena was never pointed at a bench-host | step 1 |
| `Could not resolve hostname bench.example.internal`, exit 1 | the placeholder is still in `.env` | put your real host in `.env` |
| `arena: bench ssh key not found at …`, exit 2 | `GENTAR_BENCH_KEY_FILE` does not name a readable key | export the path to the key that reaches the bench-host |
| `bench-host: … stored secrets …`, exit 2 | the bench-host's `sbx` holds stored secrets its credential proxy would hand to every sandbox | remove them on the bench-host, or set `GENTAR_SBX_SECRETS=allow` if this arena uses them on purpose |
| `port is already allocated` | another arena on the same Docker host | `GENTAR_CLICKHOUSE_HOST_PORT=8124 GENTAR_OTLP_HOST_PORT=14320 bin/arena run smoke` |
| `arena: no clickhouse up — run with GENTAR_KEEP_ARENA=1 first` | `bin/arena sql` after a normal run | re-run with `GENTAR_KEEP_ARENA=1` |

More in [Debug a red run](../guides/debug-a-red-run.md).

## Next

[Tutorial 2 — Adopt a repo](02-adopt-a-repo.md): make your own repository
a subject.
