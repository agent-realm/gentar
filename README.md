# gentar

**aGENT ARena** — a standalone end-to-end test runner, reviver, and pilot
simulator.

## What it is

You point gentar at software a person installs and uses. It brings up a
disposable machine, puts the software through the path a real user would
take — including, when the scenario asks for it, a real AI coding agent
typing at a terminal — and decides pass or fail from what is actually on
that machine afterwards: files, exit codes, processes, SQL rows, spans.
Never from what the software or the agent claims.

| Pillar | What it means |
|---|---|
| **End-to-end test runner** | one `docker-compose.yml`, disposable benches, declarative TOML suites, exit code = verdict |
| **Reviver** | every run writes a report that states what happened well enough to fix it — hand it to an agent, the loop closes |
| **Pilot simulator** | a real agent driven at a pty through onboarding dialogs and tasks, as a human pilot would be |

It runs anywhere Docker runs: a laptop, a CI runner, a server.

## Why it exists

Install paths, onboarding flows and agent-driven work break in ways unit
tests never see, and "the agent said it worked" is not evidence. gentar
answers from reality instead:

- **Verdicts from reality** — the bench's files, processes and output decide.
- **Real agents at a real pty** — `claude-code` (pinned by
  `bench-template/VERSION`) driven through its dialogs; a danger gate aborts
  anything destructive.
- **Disposable benches** — every scenario gets a fresh sbx microVM; the
  bench is the reset.
- **Semantic turns, optional** — where a regex would break on rewording, a
  typed judge (TypeSafe) answers a narrow question about the screen, or
  drives toward a goal over a closed set of actions. Synthetic data only;
  reality still decides the verdict.
- **Telemetry** — every step is a span; runs can be exported as OTLP traces
  to a collector such as ClickStack.

## How it is used

Run the engine's own suites locally. You need Docker and a bench-host (any
Linux machine with `sbx` installed and logged in once):

```bash
cp .env.example .env          # point it at YOUR bench-host + SSH key
export GENTAR_BENCH_HOST=bench.example.internal GENTAR_BENCH_USER=you
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
bin/arena run smoke           # exit code = verdict: 0 pass, 1 fail, 2 refusal
ls out/                       # report-<run_id>.md per run
```

`bin/arena` wraps the documented compose contract,
`docker compose run --rm coordinator run smoke`, and tears the stack down
on every path; `docker compose run --rm dashboard` renders a self-contained
HTML page of the runs.

Test your own repo: gentar is not installed into a repo — the repo becomes a
*subject* and the engine stays external and pinned. Three moves: **copy the
kit, own your scenarios, pin the engine version.** The kit is a `gentar/`
directory with a commented scenario, a runner, a bench-less dry-run replay,
and a workflow. Subjects mount, never bake: your checkout is staged into
each run at run time, never into an image.

```bash
cp -r path/to/gentar/subject-template/gentar ./gentar
# name the subject: subject = "<your repo>" in gentar/scenarios/*.toml
gentar/run.sh --check         # bench-free: kit drift, policy lint, dry-run
gentar/run.sh first-suite     # a real run on your bench-host
```

Agents adapting a repo: read [`AGENTS.md`](AGENTS.md) first. Humans:
[`subject-template/README.md`](subject-template/README.md).

## Documentation

| Where | What |
|---|---|
| [`docs/README.md`](docs/README.md) | the documentation index |
| [Tutorial 1 — first run](docs/tutorials/01-first-run.md) | a local run end to end |
| [Tutorial 2 — adopt a repo](docs/tutorials/02-adopt-a-repo.md) | make your repo a subject |
| [Tutorial 3 — a judged turn](docs/tutorials/03-a-judged-turn.md) | a semantic `expect` |
| [Tutorial 4 — a goal pilot](docs/tutorials/04-a-goal-pilot.md) | the judge drives toward a goal |
| guides (via [`docs/README.md`](docs/README.md)) | common operations: bench tiers, telemetry, policy and releases, fixtures |
| [runner](docs/reference/runner.md) · [reviver](docs/reference/reviver.md) · [pilot simulator](docs/reference/pilot-simulator.md) | reference: the three pillars |
| [telemetry](docs/reference/telemetry.md) · [bench tiers](docs/reference/bench-tiers.md) · [CI and releases](docs/reference/ci-and-releases.md) | reference: operating it |
| [scenario inventory](docs/reference/scenario-inventory.md) · [design tenets](docs/reference/design-tenets.md) · [layout](docs/reference/layout.md) | reference: what exists and why |
| [`docs/subject-integration.md`](docs/subject-integration.md) | the full subject contract: trigger modes, credentials, conventions |
| [`examples/README.md`](examples/README.md) | examples, from one step to a full subject |
| [`AGENTS.md`](AGENTS.md) | the agent entry: adopting a repo, deploying an arena |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed, per release |

## License

Apache-2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Relicensed from MIT to Apache-2.0 from v0.10.0; earlier releases remain MIT.
