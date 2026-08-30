---
node: /s1-subject-kernel
status: closed
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [gentar-repo, scenario-toml, sbx-linux-tier, bench-host-142]
hints: [subjects/mounted-checkouts, ci/forge-agnostic-tiers]
steered-from: none
---

# s1 — onboard kernel as subject

Path p1 from `plato/paths.md` @ plato/root. Attacks **i4 subject-coverage**.

## Mechanism

kernel — the constellation's agent-OS whose kernel is a database, and the
reference implementation of the take-your-target-from-the-environment test
pattern — becomes a gentar subject. Its repo gains a `gentar/` directory of
decision TOMLs; the arena gains the suites (carried in
`coordinator/scenarios/` per current convention until the subject-side
directory is proven in CI). Oracle-first: no LLM anywhere in the loop.

## What gets built or changed

- kernel repo: `gentar/` dir with 2-3 scenario TOMLs stating decisions —
  realm bring-up decisions, a frontdoor probe against a running realm, a
  docs-honesty anchor on kernel's README quickstart.
- gentar repo: the same TOMLs under `coordinator/scenarios/kernel-*.toml` +
  the ~10-line dispatch trigger workflow in kernel's repo.
- Suites run against a kernel realm deployed inside the bench (nested
  Docker), keeping kernel's env-driven test contract intact — REALM_URL
  points into the bench, never out to a shared host.

## What a runbook will be able to expect

- `coordinator ls` lists the new kernel suites; unknown-name refusal
  unchanged.
- A green oracle run: fresh bench, kernel quickstart executed by the
  reference solution, verdicts from files/processes/SQL inside the bench,
  spans in ClickHouse keyed by run_id.
- The dispatch trigger fires the named suite against a kernel PR head sha.

## Deliberately left out

- Real agents (deferred register). tart/macOS (deferred register). Any
  change to kernel itself beyond the `gentar/` dir + trigger — kernel's
  code is the subject under test, not the target of edits.

## Closure

- closed-reason: pilot ruling 2026-08-31 — kernel was the fan's example
  pick, not a record-backed subject; the recorded principle "subjects
  migrate to gentar when their owners choose" makes onboarding a subject
  whose owner has not asked a presumption, not generality proof. i4 is
  carried by /s3-subject-scaffold.
- do-not-retry: onboarding any specific component as a "generality proof"
  without its owner choosing to migrate. A new subject scenario starts from
  an owner's ask, not from the engine's pick.
