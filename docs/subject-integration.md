# Subject integration — wiring a repo into the gentar arena

A **subject** is any repo that wants the arena to test it. The engine is
compose-native and forge-agnostic; this doc describes the GitHub shape the
kit wires.

There is one mode: the **own arena** (below). Your repo runs the compose
stack itself: scenarios live in your repo, the run policy decides what
runs when, and the engine is a `git clone` away, pinned to a release tag.
Where the bench runs is a choice inside it:

- **A self-hosted runner** labelled `arena` on your repo (Docker and reach
  to a bench-host), or on the bench host itself in local bench mode.
- **The arena mirror**, for a PUBLIC repo: no self-hosted runner on it at
  all. A private mirror pulls it, runs phase 2 on its own runner, and
  posts the commit status `arena/phase2` back
  ([`subject-template/mirror/`](../subject-template/mirror/README.md)).

**The central arena is retired** as of 2026-10-12: see
[the record](#retired-the-central-arena) at the end.

Both start from the same kit: [`subject-template/`](../subject-template/)
in this repo — a copyable `gentar/` dir with every file and field
commented. **This document is the contract; the kit's
[README](../subject-template/README.md) is the procedure** — the
numbered steps, the commands, and what to observe after each. Read that
to adopt; read this for what the two sides owe each other.

Adoption is a process, not a copy: a subject's scenarios are updated
alongside the code they assert, and the engine version is pinned and
bumped deliberately. See [Keeping a subject
current](#keeping-a-subject-current) below, and the kit README's "When
your code changes".

## What a subject contributes

1. **Scenario configs** — the subject states install *decisions* and
   verdict assertions, not steps: TOML scenarios in the subject repo
   under `gentar/scenarios/`, which `run.sh` passes to the coordinator
   via `GENTAR_SCENARIOS_DIR`. (The engine's own `coordinator/scenarios/`
   also holds suites against real repos, such as
   `claude-playbooks-install`. Those are the engine's regression, run in
   its private mirror, not a way to adopt.)
2. **The subject checkout itself** — the working tree, staged by
   `run.sh` under `subjects/<name>/` (the files git would ship) and
   bind-mounted read-only into the coordinator; never baked into any
   image. `<name>` is the scenario's `subject`: one directory name
   (letters, digits, dot, dash, underscore; not starting with a dot or a
   dash) whose directory, symlinks resolved, is inside the subjects root.
   See [What reaches the bench](#what-reaches-the-bench).
3. **A trigger** — the kit's workflow, `gentar-arena.yml`, or for a
   PUBLIC repo its mirror variant.
4. **Maintenance** — scenarios updated in the same change as the
   behaviour they assert, and an engine pin bumped on purpose.

## What the engine guarantees

In return, and these are stable across engine versions within a major:

- **The verdict is the exit code.** `0` pass · `1` fail · `2`
  usage/config refusal. No test-report layer in between; a refusal is
  never reported as a failing test. A suite quarantined with
  `GENTAR_QUARANTINE` does not run: it exits `0` so a known flake cannot
  turn a run red, and its report says `skip`, never pass.
- **A report for every terminal outcome**, at `out/report-<run_id>.md`
  (own-arena runners copy it into the subject's `gentar/reports/`):
  every step with its output tail, every assertion with what it
  actually saw, the verdict, and a reproduce command. A failing report
  is actionable by a reader who did not watch the run.
- **Refusal before spend.** A missing credential, an unknown scenario
  name, a declared budget above the cap, or a subject name that is not
  one directory inside the subjects root exits 2 before any bench is
  created.
- **Subjects mount, never bake.** The checkout is staged at run time;
  no image built by the engine ever contains it.
- **Credential values never enter the record.** Spans and reports carry
  the NAMES a run required. Values are exported into the bench, which
  dies with the run.
- **Only the winning credential group is forwarded.** With alternatives
  declared, a stray variable belonging to a losing group cannot ride
  along and redirect the run.
- **A fresh bench per scenario.** The bench is the reset; a wedged run
  is discarded, never repaired.

## What reaches the bench

The engine ships `subjects/<name>/` into the bench workspace as it
stands, `.git` included when there is one. Before any bench exists it
refuses (exit 2):

- a `subject` that is not one directory name (`../x`, `a/b`, `..`,
  `.hidden`, `-x`, an empty string), or whose directory resolves outside
  the subjects root (a symlink out of it). A name like `../run/secrets`
  would otherwise ship the coordinator's own bench key;
- a subject whose `.git` holds a credential: in a config (user info in a
  remote or `insteadOf` URL, `http.extraheader`, `http.cookieFile`), in a
  reflog (`.git/logs/**`, where `git pull <url with a token>` writes the
  token), in `.git/FETCH_HEAD`, or in a credential store
  (`.git-credentials`, `.git/credentials`).

The engine does not filter files: what is in the directory is what the
bench gets. The stager decides:

- **The kit's `gentar/run.sh`**, for a checkout that is a git work tree
  (it has a `.git` of its own), stages the files git would ship: tracked
  files plus the untracked ones git does not ignore (`git ls-files
  --cached --others --exclude-standard`), and never `.git`,
  `gentar/.arena` or `gentar/reports`. A gitignored `.env`, `.npmrc`,
  `.netrc` or build output stays on your machine. A submodule or nested
  repository is listed by its own git, without its `.git`. If git cannot
  list a checkout that has a `.git`, staging refuses rather than copy
  everything. The dry-run stages its workspace the same way.
- **A checkout with no `.git` of its own** (an exported tarball, say) is
  copied whole, minus those three, as before: nothing tells the kit what
  to leave out, so keep secrets out of it.
- **A direct engine run** ships whatever is in `subjects/<name>/`: stage
  a fresh clone there, not a working tree with local files in it.

## Credentials (agent-in-the-loop suites)

A scenario that drives a real agent declares what it needs, by NAME —
entries are ALTERNATIVES, and a list entry is an all-of GROUP (a token
without its endpoint is half a provider and refuses):

```toml
[scenario]
# the first-party key alone, OR the token+endpoint pair together
credentials = ["ANTHROPIC_API_KEY",
               ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]]
```

The contract:

- **Missing → refuse, not fail.** The coordinator exits 2 before any
  bench exists when no alternative group is fully present in its
  environment — a usage error, never a red test (a half-present group
  refuses too; it never starts a misconfigured credentialed bench).
- **Tier-1 transport: env vars on a throwaway bench.** Present values
  are exported into every oracle step and the pty driver process
  inside the sandbox. The bench dies with the run; nothing persists.
  They never travel on a command line: each is written into an
  owner-only file inside the bench over stdin, then read, deleted and
  applied before the command runs, so no other account on the
  bench-host sees them in its process list. The osb tier, which types
  its pty command, refuses a driver scenario that forwards env
  (`credentials` or `pass_env`) (exit 2).
- **Names only in the record.** Spans and run reports carry the names
  a run required, never a value. Whatever text a run produces (an
  error, a step's output, the transcript) passes the run's scrubber
  before it reaches a report, a span or the CI log, and reports are
  owner-only files.
- **Invocation:** the credential must reach the coordinator container —
  `docker compose run --rm -e ANTHROPIC_API_KEY coordinator run agent-smoke`
  (CI maps the `ANTHROPIC_API_KEY` secret to env and passes `-e`).

## Conventions

- Scenario names are subject-local; the `subject` column in telemetry
  separates components (gauntlet policy, ported).
- A subject never gets a private sandbox image baked from its checkout.
  Subjects mount, arenas run.
- Verdicts come from reality: files, commands, processes — never from
  "the agent said it worked".
- The subject is the WORKING TREE, uncommitted changes included, minus
  what git ignores. A fix loop needs no commit to test.
- The bench-host is shared. A subject's suites clean up after
  themselves; nothing removes another arena's sandboxes or kills
  processes wholesale there.

## Keeping a subject current

A subject is a standing commitment, not a one-time wiring. Three kinds
of change, and what each obliges:

| What changed | What the subject does |
|---|---|
| the subject's code, same behaviour | nothing — phase 1 of the run policy checks the PR, and the pass is the evidence |
| what the subject DOES | update the scenarios in the SAME pull request; a scenario asserts reality, so stale reality fails honestly |
| the ENGINE | bump deliberately: re-copy the kit's files from the new release tag (the pin comes with `run.sh`), run every suite, commit the bump on its own |

The middle row is the one that decides whether an arena is worth
having. A suite that still passes after a behaviour change either
tested the change correctly or was never testing the behaviour — and a
suite going red because the thing it asserts moved is the suite doing
its job. Landing the code and the scenario in separate pull requests
leaves the default branch red in between, which teaches people to
ignore the arena.

The engine row is why the kit pins a release TAG and not a branch.
Tracking the engine's `main` means a subject's suites can change
behaviour on a day nobody touched the subject; that has happened (a kit
advertising a scenario feature the engine tip did not parse yet). The
pin is the `GENTAR_REF` default in the kit's `run.sh`, a kit file that
`--check` holds byte-identical to the pinned engine's copy, so a bump is a
re-copy of the kit, never an edit. `GENTAR_REF` in the environment (or the
`GENTAR_REF` repository variable in CI) overrides it for a run.

### The fix loop

The point of a failure is that something can act on it. Every terminal
outcome writes a report naming every step with its output, every
assertion with the actual it saw, the verdict, and a reproduce command.
On a failure: hand the report to an agent, it fixes the repo, rerun the
same suite against the working tree, iterate to green. No commit and no
CI round trip per attempt.

## Own arena — a repo runs the stack itself

gentar is compose-native; nothing about it belongs to one central
instance. What the kit's `run.sh` does for a repo (own triggers, own
conditions, reports on disk), by hand:

1. Carry scenarios in the repo (e.g. `gentar/scenarios/*.toml`,
   `subject = "<repo-name>"`).
2. In CI (or locally): clone gentar, stage this checkout under
   `subjects/<repo-name>/` (a copy of the files git would ship, as in
   [What reaches the bench](#what-reaches-the-bench) — no symlink to the
   checkout, it does not resolve through the bind and is refused), then:

   ```bash
   GENTAR_SUBJECTS_DIR="$PWD/subjects" \
     docker compose run --rm \
       -e GENTAR_SCENARIOS_DIR=/extra \
       -v "$PWD/gentar/scenarios:/extra:ro" \
       coordinator run <suite>
   ```

   (`GENTAR_SUBJECTS_DIR` is compose-interpolated into the subjects
   bind; the scenarios dir needs the explicit `-e`/`-v` pair because
   the coordinator reads it at runtime, inside the container.)
   Exit code is the verdict, same contract.

   **That invocation leaks, and must be wrapped.** `--rm` removes only
   the coordinator: `clickhouse` and `otelcol` come up via `depends_on`
   as ordinary `up` containers, and `clickhouse` owns a named volume, so
   every project strands two containers and a volume per run. Tear the
   project down after it — CI in an `if: always()` step — or copy
   `subject-template/gentar/run.sh`, which starts every service as a
   one-off `compose run -d --rm` (daemon-level `AutoRemove`, so a
   `SIGKILL`ed run still cleans up) and traps teardown on top.
3. Every run writes `out/report-<run_id>.md` — steps with output
   tails, assertions with actuals, verdict, reproduce command. On
   failure, feed that file to an agent (or a human): it states
   everything needed to act.

The one shared resource is the **bench-host** (any Linux machine with
`sbx`, reached over SSH; `GENTAR_BENCH_*` in `.env`). When the arena runs
on the bench host itself, local bench mode (`GENTAR_BENCH_HOST=local`)
calls its `sbx` directly, with no SSH user and no key. gentar ships no
bench-host and no default identifying one: `.env.example` carries
placeholders, and a tier whose install-identity vars are unset is
refused (exit 2) before any bench exists, naming the vars it needs.
Only the selected tier's vars are required, so an sbx-only install
never configures tart. The runner needs
Docker + network reachability to it — GitHub-hosted `ubuntu-latest`
can't reach an internal bench-host, so own-arena CI runs on a
self-hosted runner inside the network (any machine with Docker; the
pilot's Mac qualifies).

### Engine source

`run.sh` clones the engine over anonymous https by default, which is
all a public engine repo needs. Two knobs cover the rest:

- `GENTAR_REPO_URL` — any git URL: a fork, an internal mirror, a local
  path. Nothing else changes.
- `GENTAR_CLONE_SSH_KEY` — path to a read-only deploy key, for a
  PRIVATE engine repo. https then fails on a CI runner while a laptop
  may still succeed through a credential helper, which is how that
  difference stays hidden until CI.

### Ports

Two arenas on one Docker host collide on the published ClickHouse
(8123) and OTLP (4318) bindings. Both are env knobs the compose file
reads — `GENTAR_CLICKHOUSE_HOST_PORT` and `GENTAR_OTLP_HOST_PORT` —
and `run.sh` passes the environment through, so moving them needs no
file edit. Symptom when they collide: `port is already allocated`.

[`subject-template/`](../subject-template/) is this shape as a copyable
kit, with the adoption procedure in its
[README](../subject-template/README.md).

## Retired: the central arena

Until 2026-10-12 a subject could also dispatch `workflow_dispatch` on
`agent-realm/gentar` (with a `GENTAR_DISPATCH_TOKEN`), and gentar's own
self-hosted runner ran the named suite against the subject's pushed head
sha. **The central arena is retired**: gentar's public workflow has no
bench job any more, so such a dispatch has nothing to run. gentar's own
bench suites (the gate and nightly tiers) run in a private mirror, on
gentar's own commits only ([CI and releases](reference/ci-and-releases.md)).
The job's YAML is in this file's git history. Use the own arena.
