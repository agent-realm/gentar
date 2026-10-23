# Guide — Review an adaptation

**You want:** to know whether your suites still cover what the repo does,
after the repo has grown.

The arena cannot go stale: it is rebuilt from scratch on every run. The
**adaptation** can. A repo grows a command, a flag or an install step, the
existing suites still pass because they never mentioned it, and coverage
decays with the board still green. Nothing catches that by running.

## 1. Run the review

```bash
gentar/run.sh --review                    # since the scenarios last changed
gentar/run.sh --review --since v1.4.0     # since any ref you name
```

It needs no engine, no Docker, no bench and no secrets. It reports and
exits 0. It never fails a build and never writes a file. A bad or unknown
ref is a refusal (exit 2). In CI, a shallow checkout has no history to diff
against, so use `fetch-depth: 0`.

## 2. Read the two halves

**Names:** what the repo ships (tracked executables, and everything
under `bin/`) that no suite mentions. Each line is a question, not a
defect.

**Diff:** built from the commits, not from names, so it also sees a
change **inside** a file a suite already mentions. It reads git objects
at the ref and at `HEAD`. Uncommitted work is not in it, and two runs on
the same commits print the same thing.

| Section | What to do with it |
|---|---|
| changed paths outside `gentar/` | the full list, with renames shown as `old -> new` |
| executables: added, removed, changed | an added one probably needs an assertion; a removed one probably breaks a suite; a changed one may have new behaviour |
| suites that mention a changed path | re-read these suites against the diff: their assertions may now be too weak |
| changed paths no suite mentions | decide per path: user-facing behaviour gets a suite, an internal helper usually does not |

## 3. Decide, then propose

The review is the input to a judgement. It does not replace one. For each
gap, propose a specific assertion in the shape of AGENTS.md decision 4,
and confirm it with the pilot before writing anything. Where a regex would
be brittle, a semantic suite (decision 7) is the other kind to propose.

A suite you have written is not yet a suite that works. Report it as
written until it has exited 0 on a bench.

## What it does not cover

- `--help` output per executable. Diffing it means running the
  binaries, and that belongs on a bench, not on the host running this
  review.
- Behaviour that lives in data rather than in files: a remote API the
  repo calls, or a package version it pulls at install time.
