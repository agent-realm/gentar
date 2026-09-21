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
| credentials | `credentials = [names]` per suite (alternatives; a list entry is an all-of group) | per suite |
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

Runs a suite's steps, driver turns and assertions in a scratch `HOME` in about
a second — no bench, no sandbox, no network. A scenario is shell inside TOML,
three levels of quoting deep, and the arena was the only thing that ever ran
it: one missing quote cost a bench VM and several minutes to find. This finds
it before the push.

It is not a substitute for the arena. There is no sandbox, no template and no
network policy, so it proves the shell and the assertions while the arena
proves the isolation. Suites declaring `credentials` are skipped.

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
