# 08 — a full subject

**Shows:** everything a repo owns once it has adopted gentar, in miniature:
two suites split across the run policy's two phases, the policy itself,
and the dry-run hooks.

```
gentar/
  scenarios/example-full-install.toml   # the floor: phase 1, every default-branch push
  scenarios/example-full-upgrade.toml   # phase 2: dispatch, `arena` tag, release candidates
  policy.toml                           # which suites run when (decision 5)
  hooks.py                              # dry-run adaptations: HIDE_FROM_PATH, prepare()
```

**Introduces:** `policy.toml` (`[phase1] floor`, `bench`, `[phase2] on`,
`release_gate`) and `hooks.py` (`HIDE_FROM_PATH`, `prepare()`).

**What is NOT here, on purpose:** the kit's own files — `gentar/run.sh`,
`gentar/dryrun.py`, `gentar/plan.py`, `gentar/release-gate.sh` and
`.github/workflows/gentar-arena.yml`. They are copied **byte-identical**
from [the adoption kit](../../subject-template/README.md), and
`gentar/run.sh --check` fails when one differs from the pinned engine's
copy. A repo adapts through `scenarios/`, `policy.toml` and `hooks.py`
only.

## Run it

1. Copy the kit into your repo ([subject-template](../../subject-template/README.md)).
2. Copy this example's `gentar/` over it.
3. Then:

```bash
gentar/run.sh --check          # phase 1: lint, kit drift, dry-run — no bench
gentar/run.sh --plan           # what a PR, a main push and a release tag would run
gentar/run.sh --sweep          # every suite this environment can run
```

**Pass:** `--check` is clean, `--plan` shows the floor on a main push and
nothing bench-side on a PR, and the sweep exits `0`.
