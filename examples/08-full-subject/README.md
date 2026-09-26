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
# --plan evaluates ONE event, the one in the environment — ask per event:
GITHUB_EVENT_NAME=pull_request GITHUB_REPOSITORY=o/r PR_HEAD_REPO=o/r gentar/run.sh --plan
GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main gentar/run.sh --plan
GITHUB_EVENT_NAME=push GITHUB_REF=refs/tags/v1.0.0 gentar/run.sh --plan
gentar/run.sh --sweep          # every suite this environment can run
```

**Pass:** `--check` is clean; the three `--plan` calls show nothing
bench-side on the PR, the floor (`example-full-install`) on the main push,
and a release tag gated by `release-gate.sh` rather than run; the sweep
exits `0`.
