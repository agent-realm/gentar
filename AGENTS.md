# Adapting gentar into a repo — for the agent doing it

You are reading this because someone told you to adapt, adopt or install
gentar into a repository. This file is the procedure. The human-facing
walkthrough is [`subject-template/README.md`](subject-template/README.md);
the contract is [`docs/subject-integration.md`](docs/subject-integration.md).
Read this first, because the most important fact is the one easiest to get
wrong.

## gentar is not installed. It is adapted.

**It does not get vendored into the target repo.** No copy of this engine,
no submodule, no `pip install`. The target repo becomes a **subject**: it
grows a `gentar/` directory holding *its own* test scenarios, and the engine
stays external, cloned at run time and pinned to a release tag.

If you find yourself copying `coordinator/`, `docker-compose.yml` or
`bin/arena` into the target, stop — that is the retired per-repo-sandbox
pattern, and it is wrong here.

What you actually copy is one directory: `subject-template/gentar/` (plus
optionally `subject-template/.github/workflows/gentar-arena.yml`).

```
target-repo/
  gentar/
    scenarios/*.toml   ← the repo's own suites; you write these
    run.sh             ← clones + pins the engine, stages the checkout
    dryrun.py          ← replays steps locally, no bench
    README.md
  .github/workflows/gentar-arena.yml   ← optional, own-arena mode
```

## What a subject is for

A scenario states **install decisions and reality assertions**, never
scripts. The arena mints a disposable machine, does what the scenario says,
then asks the machine what is true — files, exit codes, processes, SQL rows,
spans. Never what the software or an agent *claims*.

The exit code is the verdict: `0` pass, `1` fail, `2` usage/config refusal,
and a refusal always happens before a bench is created.

## The five decisions

Adaptation is decisions, not a copy. Ask the pilot about anything you cannot
determine by reading the repo; do not guess and do not silently default.

| # | Decision | How to answer it |
|---|---|---|
| 1 | **Subject name** | The repo's name — **not** necessarily its directory: in a git worktree the directory is named after the branch. Write it as `subject = "…"` in every scenario; `run.sh` reads it from there and refuses `REPLACE-ME`, a bad name, or scenarios that disagree. Safe to infer; state what you chose. |
| 2 | **Trigger mode** | **Own arena** (the repo runs the stack itself, needs a self-hosted runner with Docker and reach to a bench-host) or **central dispatch** (a ~10-line job fires `workflow_dispatch` at a central arena, needs `GENTAR_DISPATCH_TOKEN` and an operator who has onboarded the repo). Ask. Outside this organisation, own arena is the only self-service path. **If own arena and the repo is PUBLIC, say this before copying the workflow:** its runner is self-hosted and persistent, and a pull request runs the PR's code on it. The kit's workflow runs only same-repository PRs, but a fork can add its own workflow aimed at that runner — so a public repo needs "Require approval for all external contributors" set, or no PR trigger at all. Let the pilot choose; do not recommend the trigger without the risk. |
| 3 | **Bench tier** | `sbx` microVM is the default and right for nearly everything. `tart` only if the repo's install is macOS-specific; `osb` / `daytona` only if the pilot already runs those. Ask before choosing anything but the default. |
| 4 | **What the first suite asserts** | **This is the work.** Read the repo: its README's install instructions, its entry points, what it puts on disk. Propose concrete assertions — a binary that answers `--version`, a config file that appears, a service that responds — and confirm them with the pilot before writing. |
| 5 | **Run policy** | Which suites run when, written once to `gentar/policy.toml` and then automated. The kit's shape: **phase 1** on every PR and default-branch push (bench-free checks on a GitHub-hosted runner, plus a floor of cheap suites on the bench for pushes), **phase 2** — the full regression — only on dispatch, the `arena` tag or a `v*-rc*` tag, and a release gated on a green phase 2 of its commit (`gentar/release-gate.sh` as the first job of the release workflow). Ask two things: **which suites form the floor**, and **whether a PR may run suites on the bench** (`[phase1] bench = "declared"`). The second puts PR code on the self-hosted runner — on a PUBLIC repo that is the pilot's security call; the kit's default is `"off"`. If the dry-run's `prepare()` needs a toolchain, declare it (`[phase1] setup = { go = "1.21" }`). Show the pilot `gentar/run.sh --plan` for a PR, a main push and a release tag before committing. |

**If a suite needs credentials, get the grouping right** — it is the
mistake the first real adopter's agent made while following this file.
`credentials` lists **alternatives**; a provider that is a *pair* is a nested
list:

```toml
credentials = ["ANTHROPIC_API_KEY",                            # this alone, OR
               ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]] # both of these
```

`["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]` flat parses fine and reads
like a pair, but means *either one*: the token wins alone, the base URL is
dropped, and the agent in the bench reports "Invalid API key". The engine now
prints a warning naming a declared credential that was set and not forwarded
— if you see one, fix the grouping; do not work around it. Validating that a
scenario *parses* is not validating that it means what you intended.

Decision 4 is where you earn your keep. The template suite asserts a
throwaway `probe.txt` so it runs green on day one; leaving it that way ships
a subject that tests nothing. A suite that asserts what the repo actually
does on a fresh machine is the entire point.

## Procedure

1. **Check the prerequisites.** Docker on the machine that will run the
   arena, and a bench-host: any Linux box with `sbx` installed and logged in
   once. No bench-host means no runs — say so rather than writing files that
   cannot work.
2. **Copy the kit.** `subject-template/gentar/` → `<target>/gentar/`, and
   the workflow if the pilot chose own-arena. Both scripts must stay
   executable (mode 755).
3. **Name the subject** (decision 1) in `gentar/scenarios/*.toml`.
4. **Stage the engine**: `gentar/run.sh --stage-engine`. Git only, no Docker.
   It clones this repo to `gentar/.arena` at the pinned tag and seeds
   `gentar/.arena/.env` from `.env.example`.
5. **Point `.env` at a real bench-host.** The seeded values are
   placeholders (`bench.example.internal`). Two failure modes worth knowing
   apart: *unset* is refused with exit 2 before any bench exists; the
   *placeholder* is a non-empty value, so nothing refuses it and the run
   fails at ssh instead.
6. **Write the real suite** (decision 4), replacing `[oracle].steps` and the
   `[[verify.*]]` assertions.
7. **Dry-run**: `gentar/dryrun.py` — replays steps and assertions locally in
   about a second, no bench. Expect `ALL PASS`. Each suite gets its own fresh
   scratch home, and `prepare()` runs once per suite: put the subject's
   binaries in that home's `~/.local/bin`, and dryrun hides those names on
   the real `PATH` so a suite can never fall through to the pilot's own
   installed copy. Names a suite creates itself go in `HIDE_FROM_PATH`. Both
   hooks live in `gentar/hooks.py`, the subject's own file; `dryrun.py` is
   the kit's and must stay byte-identical to it. It needs python 3.11+, or
   3.9/3.10 with `tomli`; if it says so, that is a missing parser on the
   host and not a problem with the suite — the arena runs 3.12 in a
   container regardless.
8. **Run for real**: `gentar/run.sh <suite>`. Exit code is the verdict; a
   report lands in `gentar/reports/`.
9. **Wire CI** (decision 2) and commit. Own arena needs three repo secrets:
   `BENCH_SSH_KEY`, `GENTAR_BENCH_HOST`, `GENTAR_BENCH_USER` (secrets, not
   variables: a public repo's logs are public). The engine ships no
   bench-host, so without them every suite fails; the workflow refuses up
   front instead. CI's own sweep is `gentar/run.sh --sweep` — every suite
   whose credentials are present, the rest skipped by name — and it tears
   down with `gentar/run.sh --down`. Write `gentar/policy.toml` (decision 5)
   and run `gentar/run.sh --check`: it is what every PR will run, and it
   fails on a kit file that differs from the pinned engine's copy — adapt
   through `hooks.py`, `policy.toml` and repository variables, never by
   editing kit files. **A local pass is not a CI pass**: the
   first push is the first time CI's environment has run it. Report CI's
   result, not your laptop's.

## Stop and ask, do not improvise

- No Docker, or no bench-host → stop. The adaptation cannot be finished.
- The engine repo is unreachable (it is private; a deploy key may be needed)
  → stop and ask how to authenticate. If a local checkout of the engine is
  already on the machine, `GENTAR_REPO_URL` can point at it — say that you
  did so, because a local path pins to whatever that checkout happens to be
  rather than to a release tag.
- You cannot tell what the repo installs or how → ask, rather than writing a
  suite that asserts nothing real.
- The pilot has not chosen a trigger mode → ask. Both are first-class and
  they need different secrets.

## Never

- **Never vendor the engine** into the target repo.
- **Never write a credential value** into a scenario, a `.env` that gets
  committed, or a report. Scenarios declare credential *names*; the values
  live in the environment and reach only the bench.
- **Never claim a suite passed without running it.** The engine exists
  because self-reported success is not evidence — do not reintroduce that at
  the adoption layer.
- **Never report the adaptation as "done" without a green run you saw.**
  Write real assertions and the scaffold is *written*, not *working*: an
  assertion nobody executed is a guess with better formatting. Until a run
  has exited 0, say **scaffolded** and name what is left — a bench-host, the
  pilot's confirmation, a first run. If the suite still asserts the
  template's `probe.txt`, say that too: it tests nothing while looking
  green.

## When the repo's code changes

Adoption is a process, not a one-time copy. A change to what the repo *does*
means its scenarios change in the same PR, because a scenario asserts
reality and stale reality fails honestly. A change to the *engine* is a
deliberate `GENTAR_REF` bump: bump it, run the suites, commit the bump on
its own. `subject-template/gentar/README.md` has the full rule.

## Running only what a change needs

You do **not** re-adapt to test a feature or a bugfix. Adaptation happens
once; which suites run is a per-run decision, and there are four ways to make
it — none of them touching `gentar/`:

| Want | Do |
|---|---|
| one suite, locally | `gentar/run.sh auth-flow` |
| several | `gentar/run.sh auth-flow config-migration` |
| one suite in CI, on any commit | push a tag `arena-auth-flow` |
| narrow a pull request | a `gentar: auth-flow` line in the PR body |

The last one works when the run policy lets a PR use the bench
(`[phase1] bench = "declared"`); it also runs the policy's floor, so a narrow
pick cannot cost the cheap guard rails. The full regression is phase 2:
dispatch, the `arena` tag or a release candidate — and a release is gated
on it. `gentar/run.sh --plan` answers "what would this event run?" without
running anything.

When a pilot asks to "run the arena for just this PR", that is the answer —
not a re-adaptation, and not a change to the arena, which is rebuilt from
scratch every run either way. If the change adds behaviour no suite asserts,
the honest move is to say so and propose a suite, not to narrow around it.

## Reviewing an adaptation

If the repo is already a subject and you are asked to check, refresh or
re-adapt it, that is this — not a re-copy of the kit, and not anything to do
with the arena. **The arena cannot go stale**: it is rebuilt from scratch on
every run, every container is `--rm`, and benches are disposable. What goes
stale is the *adaptation* — the suites versus what the repo now does.

Start with `gentar/run.sh --review`. It needs no engine, no Docker and no
bench, and it prints what the repo ships that no suite mentions, plus the
diff since the scenarios last changed.

Then do the part it deliberately does not: **read that diff and decide.** A
gap is a question, not a defect — a new internal helper may deserve nothing,
while a new install step or user-facing command probably deserves a suite.
Propose specific assertions, in the same shape as decision 4, and confirm
them with the pilot before writing.

Two honesty rules carry over. The check's blind spot is real: it compares
names, so a behaviour change *inside* a file some suite already mentions
will not appear — say so rather than implying the review was exhaustive.
And adding a suite is not the same as running one: until it has exited 0,
report it as written, not working.
