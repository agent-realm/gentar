# Guide — Debug a red run

**You want:** to turn a failing or refused run into a fix.

## 1. Read the exit code first

| Code | Meaning | Where to look |
|---|---|---|
| `0` | pass | nothing to do. If the report says "judge-flagged", a soft check was not a clear yes: read its section |
| `1` | fail: an assertion saw something reality did not support, or a step or turn failed | the report |
| `2` | refusal: a usage or configuration error, **before any bench existed** | the first `Error:` line; a report is written too |

A refusal is never a red test. Fix the invocation or the configuration,
not the code under test.


`bin/arena`'s own usage errors are not verdicts either: `64` means the
command was called wrongly (e.g. `bin/arena run` with no scenario), and
`69` means `bin/arena sql` found no ClickHouse up (run with
`GENTAR_KEEP_ARENA=1` first).
## 2. Read the report

Every terminal outcome writes one: `out/report-<run_id>.md` in the
engine, or `gentar/reports/report-<run_id>.md` in a subject repository.
It contains:

- the header: verdict, exit code, bench, and the credential **names**
  the run required;
- a **reproduce** command;
- **every step**, with its exit code and output. A failed step also
  carries the **last 40 lines of its stderr**, which is usually where the
  cause is;
- **every assertion**, with what it checked and what it actually saw;
- the **driver transcript**, when a driver ran;
- **Soft judgments**, when the scenario has `[[verify.judge]]` checks.

Hand the report to an agent with "fix the repo, rerun the suite, iterate
until it passes". It states everything needed to act.

## 3. See the spans and the dashboard

Re-run with the arena kept, then look:

```bash
export GENTAR_KEEP_ARENA=1     # every command below keeps the arena up
bin/arena run <scenario>
bin/arena sql "SELECT step, status, left(detail, 120) FROM gentar.spans ORDER BY ts_start"
bin/arena dashboard && open dashboard/out/dashboard.html
bin/arena down
unset GENTAR_KEEP_ARENA
```

In a subject repository, `gentar/run.sh` leaves `gentar/reports/dashboard.html`
after every run.

## Common refusals and their fixes

| You see | Fix |
|---|---|
| `unknown scenario '<name>'` | check the name with `bin/arena ls` |
| `bench config: sbx benches need GENTAR_BENCH_HOST and GENTAR_BENCH_USER — unset` | point the arena at your bench-host (`.env`, or the repository secrets in CI) |
| `credential guard: scenario '<name>' needs at least one of …` | set one complete credential group. A pair such as `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` needs both |
| `budget guard: run would spend …` | the scenario's `[budget] tokens` would exceed `GENTAR_BUDGET_CAP`: raise the cap on purpose, or wait |
| `judge guard: … does not declare [scenario] data = "synthetic"` | declare it, but only if nothing real is on screen |
| `judge guard: … TYPESAFE_API_KEY is not set` | lend the key with `with-secret` |
| `bench-host: … — refusing before any bench exists.` | the bench-host's own state, for example stored sbx secrets; see [Deploy an arena](deploy-an-arena.md) |
| `refusing <suite> — judged suites never run on a pull request` | expected: judged suites run in phase 2 |
| `telemetry destination needs BOTH GENTAR_OTLP_EXPORT and GENTAR_OTLP_KEY` | set both or neither |
| `arena: bench ssh key not found at …` | set `GENTAR_BENCH_KEY_FILE` to the key's path |

## Common failures

| You see | Likely cause |
|---|---|
| `Could not resolve hostname bench.example.internal` | the placeholder bench-host is still configured |
| `oracle step N failed rc=…` | read that step's output and stderr tail in the report |
| `N/M assertions failed` | the assertion table shows what reality said: fix the code, or the assertion if the behaviour changed on purpose |
| `turn N: prompt '…' never appeared` | the screen changed. Compare the driver transcript with the pattern, or make the turn judged |
| `judge never held yes … (a clear no …)` / `(undecided …)` | the question does not match the screen: measure it, see [Measure a judge with fixtures](measure-a-judge-with-fixtures.md) |
| `goal: …` | see the goal pilot's failure list in [Tutorial 4](../tutorials/04-a-goal-pilot.md) |
| `danger gate: …` | the software asked to run a destructive command. The driver refused, as designed |

## When the bench stalls

- **`sbx create` hangs for minutes:** another job may be running an sbx
  `template save` on the same bench-host, which blocks the daemon
  host-wide. Wait for it to finish, then re-run. Template builds need an
  announced window.
- **A run waits before starting:** `run.sh` prints who holds this
  subject's lock. That is another run of the same repository; it
  proceeds when that run finishes.
- **Stranded arenas after an interrupted run:** `bin/arena gc` lists
  them and `bin/arena gc --yes` removes them. It never touches a running
  arena.
