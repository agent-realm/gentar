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

## The four decisions

Adaptation is decisions, not a copy. Ask the pilot about anything you cannot
determine by reading the repo; do not guess and do not silently default.

| # | Decision | How to answer it |
|---|---|---|
| 1 | **Subject name** | The repo's directory basename. It must match `subject = "…"` in every scenario and `SUBJECT` in `run.sh`. Safe to infer; state what you chose. |
| 2 | **Trigger mode** | **Own arena** (the repo runs the stack itself, needs a self-hosted runner with Docker and reach to a bench-host) or **central dispatch** (a ~10-line job fires `workflow_dispatch` at a central arena, needs `GENTAR_DISPATCH_TOKEN` and an operator who has onboarded the repo). Ask. Outside this organisation, own arena is the only self-service path. |
| 3 | **Bench tier** | `sbx` microVM is the default and right for nearly everything. `tart` only if the repo's install is macOS-specific; `osb` / `daytona` only if the pilot already runs those. Ask before choosing anything but the default. |
| 4 | **What the first suite asserts** | **This is the work.** Read the repo: its README's install instructions, its entry points, what it puts on disk. Propose concrete assertions — a binary that answers `--version`, a config file that appears, a service that responds — and confirm them with the pilot before writing. |

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
   about a second, no bench. Expect `ALL PASS`.
8. **Run for real**: `gentar/run.sh <suite>`. Exit code is the verdict; a
   report lands in `gentar/reports/`.
9. **Wire CI** (decision 2) and commit.

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
