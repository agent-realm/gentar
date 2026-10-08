# 09: a public repository, with an arena mirror

**Shows:** the policy of a PUBLIC repository whose phase 2 runs in a
private arena mirror, plus a suite that needs a secret of its own.

```
gentar/
  policy.toml                                   # [arena] bench = "mirror", [secrets] route
  scenarios/example-reads-its-service.toml      # pass_env = ["EXAMPLE_READ_KEY"]
```

**Introduces:** `[arena] bench = "mirror"` and `mirror`,
`[phase2] evidence = "status"`, and `[secrets] route`.

**What is NOT here, on purpose:** the kit's files. In mirror mode the
public repository's workflow is the kit's public variant
(`subject-template/mirror/public/.github/workflows/gentar-arena.yml`), and
the mirror gets `subject-template/mirror/arena/`. Both are copied as they
are; see [the mirror's README](../../subject-template/mirror/README.md).

## Run it

1. Copy the kit into your repository, then this example's `gentar/` over it.
2. Replace the workflow with the public variant.
3. Set up the mirror as its README says. Add `EXAMPLE_READ_KEY` as a
   **mirror** secret, by reference.
4. Then run:

   ```bash
   gentar/run.sh --check                          # clean
   GITHUB_EVENT_NAME=workflow_dispatch gentar/run.sh --plan   # bench=none: runs in the mirror
   gentar/mirror.sh dispatch "$(git rev-parse origin/main)"   # phase 2 there, arena/phase2 here
   ```

## Passing looks like

`--plan` prints `bench=none` with a reason naming the private mirror.
`mirror.sh` prints the mirror run, `-- success`, and
`posted arena/phase2 = success`. `gentar/release-gate.sh <sha>` then passes
on that commit.
