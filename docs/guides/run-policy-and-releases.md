# Guide — Run policy and releases

**You want:** to decide once which suites run on which event, and to
refuse a release that was not proven on the bench.

The full description is in the kit's
[README](../../subject-template/gentar/README.md), under "Run policy".
The engine's own workflow is in the
[CI and releases reference](../reference/ci-and-releases.md).

## The two phases

| Event | Runs |
|---|---|
| pull request | **phase 1**: bench-free checks (`gentar/run.sh --check`: dry-run of every suite, lint, kit drift). With `[phase1] bench = "declared"`, a same-repository PR also runs the floor plus the suites its body names on a `gentar: a b` line |
| push to the default branch | **phase 1**: the checks, plus `[phase1] floor` on the bench |
| dispatch (no suites), the `arena` tag, a `v*-rc*` tag | **phase 2**: every suite this environment can run, as the job `arena / phase2`. Each trigger opts in through `[phase2] on` |
| `arena-<suite>` tag, or a dispatch naming suites | exactly those suites. This never counts as phase 2 |
| `v*` tag | nothing: a release is **gated** on a green phase 2 of its commit |

**Judged suites never run in phase 1.** That covers semantic turns, goal
pilots and soft checks: `plan.py` drops them from any phase-1 pick, and
`run.sh` refuses them on a pull request.

## Steps

1. Edit `gentar/policy.toml`. Unknown keys are refused, so a typo cannot
   silently mean a default.

   ```toml
   [phase1]
   checks = true
   bench = "off"          # or "declared"; on a public repository that is the pilot's call
   floor = []             # cheap, deterministic suites

   [phase2]
   on = ["dispatch", "arena", "rc"]
   release_gate = true
   max_age_days = 0
   ```

2. Preview what each event would run:

   ```bash
   GITHUB_EVENT_NAME=pull_request gentar/run.sh --plan
   GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main gentar/run.sh --plan
   GITHUB_EVENT_NAME=push GITHUB_REF=refs/tags/v1.2.0-rc1 gentar/run.sh --plan
   ```

3. Check it: `gentar/run.sh --check` should exit 0.

## Route your own secrets

A suite that needs a secret of your own declares it (`credentials` or
`pass_env`), and the policy routes it, by name, to the bench job:

```toml
[secrets]
route = ["SUBJECT_READ_KEY"]   # repository secrets, up to 8
```

Add the repository secret of that name. `gentar/run.sh --route` lists the
routed names, whether each arrived, and which suites declare it. Values are
never shown. The kit's workflow is unchanged, so it stays byte-identical.

## Gate a release

Make this the first job of your release workflow, and have every
publishing job depend on it (`needs: arena-gate`):

```yaml
  arena-gate:
    # the same runner as the arena's plan/checks (GENTAR_CI_RUNNER, if set)
    runs-on: ${{ vars.GENTAR_CI_RUNNER && fromJSON(vars.GENTAR_CI_RUNNER) || 'ubuntu-latest' }}
    permissions: { actions: read, contents: read }
    steps:
      - uses: actions/checkout@v4
      - run: gentar/release-gate.sh "$GITHUB_SHA"
        env: { GH_TOKEN: "${{ github.token }}" }
```

It passes only if that exact commit has a green `arena / phase2`. So:

1. Run phase 2 at the release commit, by pushing the `arena` tag or a
   `v*-rc*` tag there.
2. When it is green, push the `v*` tag.

A refusal names what it found instead: a failed or cancelled phase 2,
none at all, or, with `[phase2] max_age_days`, one that is too old.

## Check

`gentar/run.sh --plan` prints the plan for the event in your environment,
and `gentar/release-gate.sh <sha>` states its verdict on a commit.
