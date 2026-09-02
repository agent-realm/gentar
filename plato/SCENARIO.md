---
node: /s6-scaffold-honest
status: blessed
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [gentar-repo, scenario-toml]
hints: [subjects/mounted-checkouts]
steered-from: "/s4-scaffold-hardened @ 2860790"
---

# s6 — scaffold honest, round two: no holes in the exit-2 net

Steered scenario off `/s4-scaffold-hardened @ 2860790` (blessed
b1-hardened-all). Its drills — d1-tweaker, d2-abuser, d3-impatient —
confirmed the s4 hardening holds (every key-bend, rename, off-type and
overwrite attempt from the s3 round now refuses cleanly) and found the
next layer: escapes from the exit-2 net and guard blind spots. The
pilot's steer (2026-09-02, "Fix via s6") applies them as this
scenario's opening commits.

## Steers (pilot's decision, verbatim record)

Pilot chose "Fix via s6 (Recommended)" from the menu.

Findings driven in, with the drill + finding name of record:

1. **traceback escapes** — `bench = "bogus-tier"` (d1 F1), a
   recursion-bomb TOML (d2), a directory named `*.toml` (d2): all
   reach the user as raw tracebacks, exit 1 — the designed exit-2 path
   only caught TOMLDecodeError.
2. **vacuous-driver-green** (d1 F3 + d2 dup) — `[driver]
   command = "true"` with zero turns and zero probes: real bench,
   `driver ok: 0 turns`, PASS. The s4 assert guard exempted driver
   suites wholesale; a driver with no turns has no outcome.
3. **guard blind spots** (d2) — budget guard counted declared `tokens`
   only: `tokens = 0` + `simulate_spend = 500` against cap 100 ran
   green and recorded 500 units over; negative values accepted.
4. **schema gaps** (d1 F4/F5/F6) — `credentials` as a bare string
   spells its letters as env-var names; `name = ""` registers a ghost
   suite (blank `ls` line, runnable as `run ""`); duplicate names —
   in one dir, or colliding with a builtin — silently shadow.
5. **symlink escape** (d2) — `subject init --dir X --force` with a
   pre-planted symlink target writes outside the declared dir.
6. **scaffold-hint lies** (d3 F1/F2) — the closing hint's
   `GENTAR_SCENARIOS_DIR=<dir> docker compose run …` form never
   forwards the env into the container (followed verbatim, the suite
   stays unknown forever); and inside compose `--dir` writes to the
   ephemeral container filesystem with phantom success.
7. **searched-dirs silence** (d3 F3) — the unknown-scenario error
   lists dirs it cannot distinguish missing from empty; ~4 minutes of
   the eleven-minute user's life gone.

## Mechanism

- **Exit-2 net closed** — the loader's except now catches
  RecursionError and OSError alongside TOMLDecodeError; a `*.toml`
  directory is a named config error.
- **Assert guard covers vacuous drivers** — a suite asserts nothing
  when it has zero probes AND no driver-with-turns; `command = "true"`
  with no turns now refuses before any bench exists. Turns ARE verdict
  evidence; an empty turns list is not.
- **Budget guard counts real burn** — a run's spend is the larger of
  its declared ceiling and its simulated spend; negatives are refused
  at load.
- **Schema completion** — bench tier validated at load (`sbx`/`tart`);
  credentials must be a LIST of names; name must be non-empty;
  duplicate names in a dir name BOTH files; a TOML colliding with a
  builtin is a loud error, not silent builtin precedence.
- **Bounded writes** — `subject init --force` refuses symlinked
  targets rather than writing through them.
- **Hints that work verbatim** — the scaffold's closing recipe mounts
  the dir and sets the env with `-e` (`-v "$PWD/<name>-scaffold":/extra:ro
  -e GENTAR_SCENARIOS_DIR=/extra`), and says why the old form failed.
- **Errors that orient** — searched-dirs each carry their state
  (missing / empty / N suites).
- **Honesty limit stated** — the scaffold and README now say what the
  arena cannot do: force a probe to be about the subject. Tautology
  probes (`echo ok` asserting "ok") pass; the docs say so and tell the
  author what a real probe looks like.

## What a runbook will be able to expect

- `bench = "bogus"` refuses at `ls` and at `run` with exit 2 naming
  the file, key, and legal values — no traceback anywhere.
- A recursion-bomb TOML and a `*.toml` directory both refuse exit 2
  with named errors.
- A driver suite with zero turns and zero probes refuses with the
  assert-guard message; the same suite with one turn runs.
- `tokens = 0, simulate_spend = 500` against `GENTAR_BUDGET_CAP=100`
  refuses at the budget guard; negative budget values refuse at load.
- `credentials = "NAME"` (string) refuses at load naming the list
  form; `name = ""` refuses as a ghost; two files declaring one name
  refuse naming both; a user `smoke.toml` beside the builtin `smoke`
  is a loud collision error.
- `subject init --dir X --force` with a symlinked target refuses,
  bytes stay outside; the closing hint, followed verbatim, runs the
  scaffolded suite green.
- The 16 existing suites load unchanged.

## Deliberately left out

Tautology probes are documented, not detected — mechanically forcing
probe-subject relevance is judgment, and the arena's contract is
reality-checking, not authorship review (the honesty note in the
scaffold + README states the limit). Deferred-ideal topics stay
parked (deferral register). Delights recorded, unactioned.
