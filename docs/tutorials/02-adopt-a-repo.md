# Tutorial 2 — Adopt a repo

You will make your own repository a gentar **subject**. gentar is not
installed into a repo. The repo gets a `gentar/` directory holding its
own suites, and the engine stays external and pinned to a release tag.

This tutorial is the short path through the kit. The kit's own
[README](../../subject-template/README.md) is the full procedure: every
step, the command, and what you should observe. An agent adopting a repo
follows [`AGENTS.md`](../../AGENTS.md) instead, which adds the decisions
to put to the pilot.

## Prerequisites

- [Tutorial 1](01-first-run.md) done: you have a bench-host that works.
- **python 3.11+** on the machine you run from, for the local dry-run.
- **git**, and the repository you are adopting.

## 1. Copy the kit

From a checkout of this repository:

```bash
cp -R subject-template/gentar /path/to/your-repo/gentar
mkdir -p /path/to/your-repo/.github/workflows              # fine if it exists
cp subject-template/.github/workflows/gentar-arena.yml /path/to/your-repo/.github/workflows/
```

You should see: `your-repo/gentar/` holding `run.sh`, `dryrun.py`,
`plan.py`, `release-gate.sh`, `policy.toml`, `hooks.py` and
`scenarios/first-suite.toml`, plus `.github/workflows/gentar-arena.yml`.

`run.sh`, `dryrun.py`, `plan.py`, `release-gate.sh` and the workflow are
the kit's, and stay byte-identical to the pinned engine's copies. What
your repo adapts lives in files that are its own: `scenarios/`,
`policy.toml`, `hooks.py`, and repository variables.

## 2. Name the subject

```bash
cd /path/to/your-repo
sed -i.bak 's/REPLACE-ME/your-repo/' gentar/scenarios/first-suite.toml && rm gentar/scenarios/first-suite.toml.bak
grep -r REPLACE-ME gentar/ || echo "named"
```

You should see: `named`. Use the repository's name, not the name of the
directory it happens to be checked out in: in a git worktree those
differ.

## 3. Stage the engine

```bash
gentar/run.sh --stage-engine
$EDITOR gentar/.arena/.env          # GENTAR_BENCH_HOST, GENTAR_BENCH_USER
export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
```

You should see: `engine staged: …/gentar/.arena @ <tag> (<sha>)`. This
is a git operation: no Docker and no bench yet. The seeded `.env` holds
placeholders, so edit it before the next step.

## 4. Dry-run

```bash
gentar/dryrun.py
```

It replays every suite's steps and assertions in a scratch HOME in about
a second, with no bench, no Docker and no network.

You should see: `first-suite.toml: ALL PASS`, exit 0.

## 5. Run for real

```bash
gentar/run.sh first-suite
ls gentar/reports/
```

You should see: exit 0 and a `report-<run_id>.md`.

## 6. Write your real suite

Duplicate `first-suite.toml`, then replace two things:

- `[oracle].steps`: what your repo does, as shell lines run in the bench.
  State decisions (which channel, which mode, which flags), not
  keystrokes.
- `[[verify.files]]` / `[[verify.commands]]`: what must be true
  afterwards, read from reality.

Interactive paths use a `[driver]` block of turns instead of `[oracle]`.
See the [pilot simulator reference](../reference/pilot-simulator.md) and
[examples](../../examples/README.md).

```bash
gentar/dryrun.py gentar/scenarios/<your-suite>.toml
gentar/run.sh <your-suite>
```

## 7. Wire CI (own arena)

The copied workflow runs the arena on a **self-hosted runner** labelled
`arena`, which needs Docker and network reach to the bench-host. Set up
the runner and the repository secrets as in
[Deploy an arena](../guides/deploy-an-arena.md). The minimum is
`BENCH_SSH_KEY`, `GENTAR_BENCH_HOST` and `GENTAR_BENCH_USER`, all three
as secrets.

## 8. Decide the run policy

Edit `gentar/policy.toml`, which decides which suites run on a PR, on a
push, and on a release. Then check it and preview it:

```bash
gentar/run.sh --check
GITHUB_EVENT_NAME=pull_request gentar/run.sh --plan
GITHUB_EVENT_NAME=push GITHUB_REF=refs/tags/v1.0.0-rc1 gentar/run.sh --plan
```

You should see: `--check` exit 0. It runs the dry-run of every suite, the
adaptation lint and the kit-drift check, and it is what every PR runs.
See [Run policy and releases](../guides/run-policy-and-releases.md).

## 9. Commit

```bash
git add gentar .github/workflows/gentar-arena.yml
git commit -m "adopt gentar: <suite names>"
```

`gentar/.arena/` and `gentar/reports/` are gitignored and must stay that
way.

## When it fails

- `subject is still the template placeholder (REPLACE-ME)`: step 2.
- `--check` says a kit file differs from the pinned kit's copy: re-copy it
  from the engine at your pin. Adapt through `hooks.py`, `policy.toml` and
  repository variables, never by editing kit files.
- Anything at run time: [Debug a red run](../guides/debug-a-red-run.md).

## Next

[Tutorial 3 — A judged turn](03-a-judged-turn.md).
