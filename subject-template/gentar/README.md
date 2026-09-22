# <REPO> × gentar (own arena)

This repo carries its own [gentar](https://github.com/agent-realm/gentar)
arena: scenarios live here, run here, and every run writes a report you
can hand to an agent to fix what failed.

## What this directory declares

A subject states five things, all of them in this directory:

| Declaration | Where | This repo's value |
|---|---|---|
| subject name | `subject = "…"` in every scenario TOML + `SUBJECT` in `run.sh` | `<REPO>` |
| suites | `scenarios/*.toml` — decisions + reality assertions | see below |
| credentials | `credentials = [names]` per suite — entries are alternatives; missing them all refuses (exit 2) before a bench exists. Keep them flat: all-of groups (a nested list) are not in the engine on `main` yet | per suite |
| trigger | `.github/workflows/<arena workflow>` (or a dispatch job into the central arena) | see workflow |
| engine pin | `GENTAR_REF` (default `main`), re-fetched every run | `main` |

## Quickstart (local)

Prereqs: Docker, and network reach to a **bench-host** (any Linux
machine with [`sbx`](https://github.com/docker-sandbox) — the default
`.env` points at the shared one; change it if you host your own).

```bash
gentar/run.sh first-suite   # the template suite — proves the plumbing
ls gentar/reports/          # report-<run_id>.md per run
```

First run clones gentar into `gentar/.arena` and seeds `.env` from
`.env.example` — edit that if your bench-host differs.

Exit code is the verdict: `0` pass · `1` fail · `2` usage/config
refusal.

A run leaves no containers or volumes behind, guaranteed twice over.
(Plain `docker compose run --rm` would not: `--rm` removes only the
coordinator, while `clickhouse` and `otelcol` come up via `depends_on` as
ordinary `up` containers and `clickhouse` owns a named volume.)

- **Every container is `--rm`.** The compose spec has no per-service
  auto-remove key and `compose up` has no `--rm`, so the runner starts
  each arena service as a one-off `compose run -d --rm` — the only way to
  get daemon-level `AutoRemove`. A stopped container is then removed by
  the Docker daemon itself, whatever stopped it: ctrl-c, `SIGKILL`, OOM,
  or the runner dying before its trap can fire.
- **A trap tears the project down anyway** — pass, fail, refusal and
  ctrl-c alike — covering the network and anything else left over.

To keep a stack up and inspect ClickHouse, set `GENTAR_KEEP_ARENA=1`; you
then own the teardown, which the runner prints as two commands. Both are
needed: `compose down` alone refuses the network with "Resource is still
in use", because it does not stop one-off containers.

## The fix loop

A failing run writes `gentar/reports/report-<run_id>.md` stating: what
ran (every step, with output), what was asserted and what it actually
saw, and a reproduce command (`gentar/run.sh <suite>` — the runner
rewrites the engine's central-arena default on copy). Feed it to an
agent:

Read gentar/reports/report-<id>.md, fix the repo, rerun
`gentar/run.sh <suite>`, iterate until pass.

The subject is your **working tree** (uncommitted changes included) —
fix and rerun, no commit needed to test.

The engine is pinned by `GENTAR_REF` (default `main`), re-fetched and
re-checked-out on every run, **and the coordinator image is rebuilt from it**.
That last part is not optional: the compose service is `build: ./coordinator`,
so without a build step `docker compose run` reuses a cached image, and on a
long-lived runner that image drifts months behind the source while `GENTAR_REF`
looks perfectly honoured. A fresh checkout is not a fresh engine.

## Suites

| Suite | Proves |
|---|---|
| `first-suite` | the template suite — arena plumbing only; replace with your first real suite |

## Before you push a suite

```bash
gentar/dryrun.py                                   # every suite
gentar/dryrun.py gentar/scenarios/first-suite.toml
```

Runs a suite's steps, driver turns and assertions in a scratch home in about
a second — no bench, no sandbox, no network. A scenario is shell inside TOML,
three levels of quoting deep, and the arena was the only thing that ever ran
it: one missing quote cost a bench VM and several minutes to find. This finds
it before the push.

The layout mirrors a bench: your checkout is staged into `WORKSPACE_DIR`,
which sits *under* `HOME` rather than being it, and steps run with the
workspace as cwd. So a `~/…` assertion asks about the pilot's home, never
about a file that shipped in your repo.

It is not a substitute for the arena. There is no sandbox, no template and no
network policy, so it proves the shell and the assertions while the arena
proves the isolation. Two kinds of suite it will not claim to have checked:
those declaring `credentials` are skipped (they need a real agent and a real
key), and those whose `[driver]` uses `pick` or `abort` turns come back
`UNVERIFIED` with a nonzero exit — those need the real driver, and a picker
that never matched must not read as a pass.

Add a suite = add a TOML here. Schema and vocabulary:
[gentar scenario schema](https://github.com/agent-realm/gentar/blob/main/coordinator/gentar/toml_scenario.py)
— decisions and reality assertions, never scripts.

## CI (`.github/workflows/`)

The arena workflow runs every suite on push (edit its `on:` block to
taste — triggers are yours, the arena doesn't care). It needs a
self-hosted runner labeled `arena` with Docker + reach to the
bench-host; GitHub-hosted runners cannot reach an internal bench-host.
One-time setup, ~5 min on any always-on machine with Docker:

GitHub → this repo → Settings → Actions → Runners → New self-hosted
runner → follow the commands → when configuring, labels: `arena`.

Secrets/vars the workflow reads (all optional; unset agent credentials
simply leave agent suites out of the sweep):

- `secrets.BENCH_SSH_KEY` — key the coordinator uses to reach the bench-host
- `secrets.GENTAR_CLONE_KEY` — read-only deploy key on agent-realm/gentar (private repo)
- `secrets.ANTHROPIC_API_KEY` or `secrets.ANTHROPIC_AUTH_TOKEN` + `vars.ANTHROPIC_BASE_URL` — agent suites
- `vars.ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU,FABLE}_MODEL` — all four, for a routed endpoint
- `GENTAR_BUDGET_CAP` in the workflow — ceiling the budget guard enforces

The workflow stages the checkout exactly like `run.sh` does, so local
and CI run the same way.

## Layout

```
gentar/
  scenarios/*.toml   # suites (this repo's own)
  run.sh             # local kickoff — stage, run, report
  dryrun.py          # local, bench-less step/assertion replay
  reports/           # run reports land here (gitignored)
  .arena/            # gentar checkout (gitignored, auto-cloned)
```
