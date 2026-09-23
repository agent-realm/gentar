# Subject template — the adoption kit

Copy this directory into a repo and that repo becomes a gentar
**subject**: it carries its own suites, runs them against real benches,
and gets a report it can act on when one fails.

Adoption is a **process, not a one-time copy**. The kit gets you to a
first green run; the last section — [When your code
changes](#when-your-code-changes) — is the part that keeps it honest
afterwards, and it is the reason a subject is worth having at all.

The full contract (what a subject provides, what the engine guarantees)
is [`docs/subject-integration.md`](../docs/subject-integration.md). This
page is the procedure. They must agree; where one is more specific, it
says so.

## What a subject declares

Five declarations, all in the copied `gentar/` directory plus one
workflow:

| # | Declaration | Where it lives | Default the kit gives you |
|---|---|---|---|
| 1 | **Subject name** | `subject = "…"` in every scenario TOML — `run.sh` reads it from there | `REPLACE-ME`, refused until set |
| 2 | **Suites** | `gentar/scenarios/*.toml` — install *decisions* + reality assertions, never scripts | `first-suite.toml`, fully commented |
| 3 | **Credentials** | `credentials = [names]` per suite — env var NAMES; entries are alternatives, a list entry is an all-of group; none = oracle suite | none (first-suite is credential-less) |
| 4 | **Trigger** | `.github/workflows/gentar-arena.yml` (own arena, kept byte-identical to the kit) and/or a dispatch job (central arena) | own-arena workflow: PRs, push to main, tags, dispatch — what each runs is the run policy's |
| 5 | **Engine pin** | `GENTAR_REF` in `run.sh` | `v0.4.1` — a release tag, bumped deliberately |
| 6 | **Run policy** | `gentar/policy.toml` — phase 1 on PRs and main pushes, phase 2 (full regression) on dispatch / `arena` / `v*-rc*`, releases gated by `gentar/release-gate.sh` | PRs bench-free (`bench = "off"`), empty floor, gate on |
| 7 | **Dry-run hooks** | `gentar/hooks.py` — `prepare()`, `HIDE_FROM_PATH`, `SKIP_STEP_SUBSTR` | no-ops |

The verdict contract is the engine's, not yours: exit `0` pass · `1`
fail · `2` usage/config refusal. Assertions read reality — files,
processes, command output — never "the agent said it worked".

## Prerequisites

- **Docker** on the machine that runs the arena (your laptop, or a
  self-hosted CI runner). The arena itself is a compose stack.
- **A bench-host of your own**: any Linux machine reachable over SSH
  with [`sbx`](https://docs.docker.com/ai/sandboxes/) installed and
  logged in once. Benches are microVMs it spawns; they are not compose
  services. The engine ships no default host — you name yours.
  Other tiers exist (macOS VMs via tart, containers via OpenSandbox,
  cloud sandboxes via Daytona) and are selected per scenario — the kit
  defaults to sbx.
- **git** and **python 3.11+** for the local dry-run.

You do not need an account, a token, or anything hosted. Nothing in this
kit assumes the engine and the subject share an owner.

## The procedure

Nine steps. Each states the command and what you should observe; if an
observation does not match, stop there — the later steps assume it.

### 1. Copy the kit

From a checkout of the engine repo, into your repo:

```bash
cp -R subject-template/gentar  /path/to/your-repo/gentar
cp -R subject-template/.github /path/to/your-repo/.github   # merge if you have one
```

Observe: `your-repo/gentar/` contains `run.sh`, `dryrun.py`, `plan.py`,
`release-gate.sh`, `policy.toml`, `hooks.py`,
`scenarios/first-suite.toml`, `.gitignore`, `README.md`, and
`your-repo/.github/workflows/gentar-arena.yml` exists.

Four of those are the kit's and stay **byte-identical** to the pinned
engine's copies: `run.sh`, `dryrun.py`, `plan.py`, `release-gate.sh`, plus
the workflow. `gentar/run.sh --check` fails when one differs, so an engine
bump is a re-copy, never a merge. Everything a repo adapts lives in files
that are its own: `scenarios/`, `policy.toml`, `hooks.py`, and repository
variables.

`gentar/.gitignore` keeps `reports/`, `.arena/` and `.env` out of git.
Check it landed — those three carry run output, a whole engine checkout,
and possibly a bench key:

```bash
cd /path/to/your-repo && git check-ignore -v gentar/.arena/ gentar/reports/ gentar/.env
```

Observe: three lines, one rule each. The trailing slashes matter —
`reports/` and `.arena/` are directory patterns, and `git check-ignore`
will not match one against a path that does not exist yet unless you
spell it as a directory.

### 2. Name the subject

The subject name is the directory your checkout is staged under, and the
`subject` column in telemetry. It must match in two places:

```bash
cd /path/to/your-repo
sed -i.bak 's/REPLACE-ME/your-repo/' gentar/scenarios/first-suite.toml && rm gentar/scenarios/first-suite.toml.bak
grep subject gentar/scenarios/first-suite.toml
```

`run.sh` derives the same name from your repo's directory basename, so
if the directory is `your-repo`, you are done. Edit `SUBJECT` in
`run.sh` only when the two must differ.

Observe: `subject = "your-repo"` and no `REPLACE-ME` left:
`grep -r REPLACE-ME gentar/` prints nothing.

### 3. Stage the engine

```bash
gentar/run.sh --stage-engine
```

Clones the engine into `gentar/.arena`, checks out the pinned
`GENTAR_REF`, and seeds the arena's `.env` from its `.env.example`. No
Docker, no bench — this is a git operation.

Observe: `engine staged: …/gentar/.arena @ v0.4.1 (<sha>)` and a path to
the arena env file.

**The seeded `.env` holds placeholders, not a working config — edit it
before the next step.** gentar ships no bench-host of its own, so
`GENTAR_BENCH_HOST` arrives as `bench.example.internal` and
`GENTAR_BENCH_USER` as `bench`:

```bash
$EDITOR gentar/.arena/.env     # GENTAR_BENCH_HOST, GENTAR_BENCH_USER
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"   # the key that reaches it
```

Observe: `grep -E '^GENTAR_BENCH_(HOST|USER)' gentar/.arena/.env` names
YOUR machine and account, with no `example` left in either.

The two failure modes if you skip this, so you can tell them apart:

- **Left unset** (empty value) — the coordinator refuses before any
  bench exists: `bench config: sbx benches need GENTAR_BENCH_HOST and
  GENTAR_BENCH_USER — unset`, exit 2.
- **Left as the placeholder** — it is a non-empty value, so nothing
  refuses it; the run reaches ssh and dies with `Could not resolve
  hostname bench.example.internal`, exit 1. A name gentar cannot check
  is a name you must get right.

`GENTAR_BENCH_KEY_FILE` is a path on the machine running the arena; the
key is mounted into the coordinator, never copied into a bench. Set it
in the shell or in that same `.env` — `run.sh` checks whichever compose
resolves, and refuses with exit 2 naming the path if it is unreadable.

### 4. Dry-run the template suite

```bash
gentar/dryrun.py
```

Replays every suite's steps, driver turns and assertions in a scratch
HOME in about a second. No bench, no Docker, no network. A scenario is
shell inside TOML, three levels of quoting deep, and this finds the
missing quote before it costs a bench.

Observe: `first-suite.toml: ALL PASS`, exit 0.

### 5. Run it for real

```bash
gentar/run.sh first-suite
```

Builds the coordinator image from the pinned engine, brings up the arena
(ClickHouse + otelcol + coordinator), spawns a bench on the bench-host,
runs the suite there, asserts reality, tears everything down.

Observe: exit 0, and a report:

```bash
ls gentar/reports/          # report-<run_id>.md
```

A run leaves no containers, volumes or networks behind. Verify against
your own project label rather than global counts — another arena may be
running on the same host:

```bash
docker ps -a --filter label=com.docker.compose.project=arena-your-repo
docker volume ls -q | grep '^arena-your-repo' || echo "no volumes"
```

Observe: both empty.

If two arenas share a Docker host, their published ports collide
(`port is already allocated`). Move yours — the engine's compose file
reads both as env knobs, so no file edit is needed:

```bash
GENTAR_CLICKHOUSE_HOST_PORT=8124 GENTAR_OTLP_HOST_PORT=14320 \
  gentar/run.sh first-suite
```

Green here means the whole chain works: staging, engine pin, image
build, bench lifecycle, assertions, reporting. Everything after this is
your content, not plumbing.

### 6. Write your first real suite

Duplicate `first-suite.toml` and replace two things:

- `[oracle].steps` — what your repo *does*, as shell lines run inside
  the bench. State decisions (which channel, which mode, which flags),
  not a transcript of keystrokes.
- `[[verify.commands]]` / `[[verify.files]]` — what must be **true
  afterwards**, read from reality.

The vocabulary is the scenario schema, which the engine carries at
`coordinator/gentar/toml_scenario.py` (in `gentar/.arena/` after step
3 — the pinned copy, which is the one that will parse your suite).
Interactive paths get a `[driver]` block instead of `[oracle]`: turns at
a pty, so onboarding dialogs and confirmation prompts become testable.

Keep or delete the template suite. Then repeat steps 4 and 5 for the new
suite:

```bash
gentar/dryrun.py gentar/scenarios/<your-suite>.toml
gentar/run.sh <your-suite>
```

Observe: `ALL PASS` then exit 0. A failing run writes a report — see
[the fix loop](#the-fix-loop).

### 7. Pick a trigger mode

Two modes, and they coexist. Both are first-class; the difference is who
runs the arena.

**Own arena** — the copied workflow. Your repo runs the compose stack
itself, on your triggers, and reports land in your `gentar/reports/`.
Needs a self-hosted runner labeled `arena` (Docker + network reach to
the bench-host; a GitHub-hosted runner cannot reach an internal
bench-host). One-time setup, about five minutes on any always-on machine
with Docker: repo → Settings → Actions → Runners → New self-hosted
runner → labels: `arena`.

Secrets and vars it reads:

| Name | Kind | When you need it |
|---|---|---|
| `BENCH_SSH_KEY` | secret | always — the key the coordinator uses to reach the bench-host |
| `GENTAR_BENCH_HOST` | secret | always — the engine ships no bench-host; unset, the workflow refuses before staging anything |
| `GENTAR_BENCH_USER` | secret | always — the account on it |
| `GENTAR_CLONE_KEY` | secret | only if the ENGINE repo is private (read-only deploy key on it) |
| `GENTAR_REPO_URL` | var | only to point at a fork or mirror of the engine |
| `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` | secret / var | only for agent-in-the-loop suites |

The three bench-host values are **secrets rather than variables** because a
public repo's Actions logs are public: secrets are masked, variables print.
Unset agent credentials simply leave those suites out of the sweep, with a
line in the log saying which and why.

**Pull requests and the self-hosted runner.** The workflow always triggers on
pull requests, but what a PR runs is the run policy's: with the kit's default
(`[phase1] bench = "off"`) a PR runs only bench-free checks on a GitHub-hosted
runner and never reaches the self-hosted one, and a fork's PR never does
whatever the policy says. A fork can still add its own workflow aimed at the
runner, so on a public repo also set "Require approval for all external
contributors".

**Central arena** — a ~10-line dispatch job in your repo fires a
`workflow_dispatch` at a gentar instance someone else operates, passing
your PR head sha as the subject ref. Nothing to host; you need a
`GENTAR_DISPATCH_TOKEN` and the arena side needs read access to your
checkout. The exact job and both token scopes are in
[`docs/subject-integration.md`](../docs/subject-integration.md).

Observe either way: open a pull request touching anything, and the
arena runs against its head commit.

**Before it merges**, prove the adoption PR on the bench by pushing the
`arena` keyword tag at its head commit. A tag push
runs the workflow file of the *tagged* commit, even when that file is not
on the default branch yet — which is how the first real adoption got a CI
arena before merge.

### 8. Pin the engine

`run.sh` defaults `GENTAR_REF` to a **release tag**, not a branch. The
engine is a separate repo on its own cycle: tracking `main` means your
suites can change behaviour on a day nobody touched your code. That is
not hypothetical — this kit once advertised a scenario feature the
engine's tip did not parse yet, and adopters saw a load error they had
not caused.

Check what you are pinned to, and what exists:

```bash
grep -n '^REF=' gentar/run.sh                      # the pin in force
git -C gentar/.arena fetch -q --tags origin        # what the engine offers
git -C gentar/.arena tag -l 'v*' | sort -V | tail -5
```

Observe: one `REF=${GENTAR_REF:-<tag>}` line, and the available release
tags. An empty tag list means the engine has published none yet — pin a
SHA instead, never a branch.

To move, change the default in `run.sh`, run your suites, and commit the
bump as its own change with the result in the message. `GENTAR_REF=main`
stays available per-run for anyone tracking the engine deliberately.

### 9. Commit

```bash
git add gentar .github/workflows/gentar-arena.yml
git commit -m "adopt gentar: <suite names>"
```

`gentar/.arena/` and `gentar/reports/` are gitignored and must stay that
way — the first is a whole engine checkout plus an `.env` that can hold
a bench key, the second is per-run output.

## When your code changes

Adoption is not finished at the first green run. A suite asserts what is
**true of your repo**, so the two move together — and that is the whole
value: a scenario that still passes after a behaviour change either
tested the change correctly or was never testing the behaviour.

Three kinds of change, three responses:

**Your code changed, its behaviour did not.** Nothing to do. The PR
trigger re-runs your suites against the change before it lands; a pass
is the evidence the refactor was one.

**What your repo DOES changed.** The scenarios change in the **same
pull request**. A scenario states reality, so stale reality fails —
honestly and loudly, which is correct. Treat "a suite went red because
we changed the thing it asserts" as the suite doing its job, and update
the assertion to the new truth in the same change that creates it.
Splitting them across two PRs means main is red in between, and a red
main teaches people to ignore the arena.

New behaviour usually means a new suite rather than an edited one.
Dry-run it (step 4), run it once for real (step 5), and it ships with
the feature.

**The ENGINE changed.** Nothing happens until you say so — that is the
point of pinning to a release tag. Bumping is a deliberate act: change
the default in `run.sh`, run every suite, and commit the bump with the
outcome in the message. If a suite fails on the new engine, the bump is
the change under test and belongs in its own PR, never smuggled in with
a feature.

### The fix loop

This is what the arena is *for*. Every terminal outcome — pass, fail,
refusal — writes `gentar/reports/report-<run_id>.md` stating what ran
(every step, with its output), what was asserted, what it actually saw,
and a reproduce command. On a failure that file is a work order, not a
log:

```
Read gentar/reports/report-<id>.md, fix the repo, rerun
`gentar/run.sh <suite>`, iterate until it passes.
```

Hand it to an agent or read it yourself; it states everything needed to
act without the reader having seen the run. The subject is your
**working tree**, uncommitted changes included, so the loop is
fix-and-rerun — no commit, no push, no CI round trip per attempt.

Two failure shapes to read differently. Exit `1` is a real verdict: the
assertion saw something other than what was claimed. Exit `2` is a
refusal before any bench existed — a missing credential, an unknown
scenario name, a budget cap below the suite's declared spend. A refusal
is a usage error to fix in the invocation, never a red test.

## Conventions (the ones that bite)

- **Subjects mount, never bake.** Your checkout is staged as
  `subjects/<name>/` at run time; no image ever carries it. A per-repo
  sandbox image with a baked checkout is the retired anti-pattern this
  kit exists to prevent.
- **Working tree is the subject** — uncommitted changes included. That
  is what makes the fix loop cheap, and it means a run tests what is on
  disk, not what is committed.
- **A fresh checkout is not a fresh engine.** `run.sh` re-fetches
  `GENTAR_REF` *and rebuilds the coordinator image* every run. The
  compose service is `build: ./coordinator`, so without the rebuild
  `docker compose run` reuses a cached image — and on a long-lived
  runner that image drifts months behind the source while `GENTAR_REF`
  looks perfectly honoured. Do not delete the build step to save time.
- **Secrets travel by name only.** Credential VALUES reach the bench as
  env vars on a throwaway; spans and reports carry the names a run
  required, never a value.
- **Scenario names are subject-local.** Two subjects may both have an
  `install` suite; the `subject` column separates them.
- **The bench-host is shared.** Other arenas may be using it. Never kill
  processes wholesale there, and remove only sandboxes your own run left
  behind.

## Kit layout

```
subject-template/
  gentar/                          # → <your-repo>/gentar/
    README.md                      # subject-side doc (fill in the tables)
    scenarios/first-suite.toml     # every field, commented
    run.sh                         # stage, run, report; --check --plan --down
    dryrun.py                      # bench-less replay (~1s)
    plan.py                        # the run policy's only reader
    release-gate.sh                # may this commit be released?
    policy.toml                    # YOURS: which suites run when
    hooks.py                       # YOURS: dry-run hooks
    .gitignore                     # reports/ .arena/ .env
  .github/workflows/gentar-arena.yml   # → your workflows dir
```
