# Guide: an arena for a public repository

**You want:** phase 2 on a self-hosted bench for a PUBLIC repository,
without registering a self-hosted runner a fork could reach.

The answer is an arena **mirror**. The public repository keeps only
GitHub-hosted plan and checks. A private mirror pulls it, verifies the
commit, runs phase 2 on its own runner, and reports back as the commit
status `arena/phase2`.

The setup, the trust rules and the day-to-day commands are in the kit:
[subject-template/mirror/README.md](../../subject-template/mirror/README.md).
A worked policy is in [example 09](../../examples/09-public-repo-mirror/README.md).

## Steps

1. Set `[arena] bench = "mirror"`, `mirror = "owner/name-arena"` and
   `[phase2] evidence = "status"` in `gentar/policy.toml`.
2. Replace `.github/workflows/gentar-arena.yml` with the kit's public
   variant (`subject-template/mirror/public/`).
3. Copy `subject-template/mirror/arena/` into the private mirror. Set its
   variables and secrets, and register its runner (label `arena`).
4. Remove the public repository's runner and bench secrets.
5. Run `gentar/mirror.sh dispatch <sha>` once on the default-branch head.

## Check

- `gentar/run.sh --check` is clean. It refuses a public variant that
  drifted, and a policy that still asks for a bench here.
- `GITHUB_EVENT_NAME=workflow_dispatch gentar/run.sh --plan` says phase 2
  runs in the private mirror.
- `gentar/mirror.sh status <sha>` shows `arena/phase2: success` after a
  green run.
