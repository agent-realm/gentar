# Arena mirror: phase 2 for a public repository

**Use this when the repository is PUBLIC.** A self-hosted runner registered
to a public repository can be reached by a fork: it adds its own workflow
file to a pull request, and only an approval click stands between that
file and a runner holding your bench key. The kit's default workflow
refuses fork PRs in its own jobs, but cannot refuse a workflow it did not
write.

The fix is to register no self-hosted runner there at all.

- The **public repository** runs the kit's *public variant* workflow. It has
  plan and checks only, both GitHub-hosted, and no self-hosted job.
- A **private mirror repository** holds its own workflow and runs phase 2
  on the self-hosted runner. It **pulls** the public repository; nothing
  pushes to it, and the public repository holds no token for it.
- The result comes back to the public commit as the commit status
  **`arena/phase2`**, which the release gate reads.

```
public repo (owner/name)                       private mirror (owner/name-arena)
  .github/workflows/gentar-arena.yml  <-- this    .github/workflows/arena.yml  <-- arena/
    (public/ variant: plan + checks)               verify-ref.sh, route.py      <-- arena/
  gentar/  (the kit, as usual)
  gentar/policy.toml: [arena] bench = "mirror"     runner: label `arena`
                                                   secrets: bench key, provider keys,
       gentar/mirror.sh dispatch <sha> ---------->    routed secrets, GENTAR_STATUS_TOKEN?
       <------ commit status arena/phase2 --------
```

## What admits a commit

The mirror runs the public repository's `gentar/run.sh` on its runner, with
the bench key. So admitting a commit means trusting whoever could write it.
`verify-ref.sh` admits a commit only when it is reachable from:

- the public repository's **default branch**, or
- a **`v*` tag**, or
- **any branch head**, but only when the mirror's variable
  `GENTAR_ALLOW_BRANCH_HEADS` is `true`. Off by default. Turn it on to gate
  pull requests on phase 2 before merging. Only collaborators can create
  branches in the base repository; a fork's commits live under
  `refs/pull/*`, which is never fetched.

GitHub serves **any** commit of a fork network by sha through the parent
repository's URL, so a fetch that succeeds proves nothing. `verify-ref.sh`
fetches only the refs above, into an empty repository, then checks
ancestry. The bench job checks out the verified sha and nothing else.
`allow_branch_heads` is read only from the **mirror's** variable, never
from the public repository's files, so a branch cannot widen its own
admission.

The same holds for secrets. The mirror's variable `GENTAR_ROUTE_ALLOW`
names the subject secrets it will route, and it is the upper bound. A
commit's `[secrets] route` can only narrow it: a name the mirror does not
allow gets an empty slot, and the plan job names it (the name only).
`route.py` reads the commit's policy as data; the plan job runs none of
the public repository's code. So a branch that edits its own policy, or
its `plan.py`, still reaches no secret the mirror did not offer.

## Set it up

1. **The public repository.**
   - In `gentar/policy.toml`:

     ```toml
     [phase1]
     bench = "off"            # no bench runner here
     floor = []

     [phase2]
     evidence = "status"      # the release gate reads arena/phase2

     [arena]
     bench = "mirror"
     mirror = "owner/name-arena"
     ```

   - Copy `subject-template/mirror/public/.github/workflows/gentar-arena.yml`
     over `.github/workflows/gentar-arena.yml`. `gentar/run.sh --check`
     holds the file to this variant byte for byte once the policy says
     `bench = "mirror"`.
   - Deregister any self-hosted runner, and delete the bench secrets
     (`BENCH_SSH_KEY`, `GENTAR_BENCH_USER`, provider keys).

2. **The mirror** (private, created by whoever owns the organisation).
   - Copy `subject-template/mirror/arena/` into its root:
     `.github/workflows/arena.yml`, `verify-ref.sh` and `route.py`.
   - Variables:
     - `GENTAR_PUBLIC_REPO = owner/name`
     - `GENTAR_ALLOW_BRANCH_HEADS = true` (optional)
     - `GENTAR_ROUTE_ALLOW = "NAME_A NAME_B"`: the subject secrets this
       mirror will route (empty: none). `GENTAR_*`, `GITHUB_*`,
       `ACTIONS_*`, `RUNNER_*` and `BENCH_SSH_KEY` are refused.
     - the kit bench job's own: `GENTAR_BENCH_HOST`, `GENTAR_REF`,
       `ANTHROPIC_BASE_URL`, the model pins, the host ports.
   - Secrets, set by reference (`with-secret`, piped), never pasted:
     - `BENCH_SSH_KEY`, `GENTAR_BENCH_USER`
     - the provider keys the agent suites need
     - every name in `GENTAR_ROUTE_ALLOW`
     - optionally `GENTAR_STATUS_TOKEN`: a fine-grained token allowed to
       write commit statuses on the public repository, so the mirror posts
       `arena/phase2` itself.
   - Register the self-hosted runner to the mirror, label `arena`.

3. **Prove it once**, on the current default-branch head:
   `gentar/mirror.sh dispatch <sha>`. Then check that `arena/phase2` shows
   on the public commit.

## Day to day

| You want | Do |
|---|---|
| phase 2 on a commit | `gentar/mirror.sh dispatch <sha>`: dispatch, wait, post `arena/phase2` (exit 0 green) |
| a few suites | `gentar/mirror.sh dispatch <sha> suite-a suite-b`: a targeted run, never posts the status |
| what a commit has | `gentar/mirror.sh status <sha>` |
| the default branch covered | the mirror's daily schedule; a no-op when that head is already green there |
| a release | `gentar/release-gate.sh <sha>` passes on a success `arena/phase2` on exactly that sha |

`mirror.sh` needs `gh`, authenticated as someone who can run the mirror's
workflows and write commit statuses on the public repository. The status
links the mirror run, which is private: only people who can read the
mirror can follow the link.

## Vendoring `verify-ref.sh`

`verify-ref.sh` is self-contained. Another mirror (gentar's own, say) can
carry one copy, with a line naming the gentar tag it came from and its
sha256. Re-vendor it at every kit bump.

## Not covered

- **No live proof in this release.** Every piece is tested against
  fixtures, including a server that serves a fork's commit by sha. The
  first live run is the first adopter's cutover.
- **Freshness depends on an artifact.** The scheduled no-op looks for a
  `phase2-green-<sha>` artifact, so it expires with the mirror's artifact
  retention, and the run after that sweeps again.
- **The schedule is fixed:** daily, in `arena.yml`. Another cadence is a
  deliberate edit of the mirror's copy.
