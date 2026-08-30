---
node: /s3-subject-scaffold
status: proposed
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [gentar-repo, scenario-toml]
hints: [ci/forge-agnostic-tiers, subjects/mounted-checkouts]
steered-from: none
---

# s3 — subject scaffold generator

Path p3 from `plato/paths.md` @ plato/root. Attacks **i4 subject-coverage**.

## Mechanism

"Any component becomes a subject with minimal moves" becomes mechanical: a
coordinator subcommand (`gentar subject init <name> --repo <url>`) emits a
working skeleton — a decision-TOML scenario pre-filled with the subject's
install decision, a verify probe stub, the budget block, and the exact
~10-line trigger workflow for the subject's repo — so onboarding is one
command plus filling in the assertions only the subject's author knows.

## What gets built or changed

- gentar repo: new `gentar subject init` subcommand (pure generator, no
  network required to emit), template rendering from the existing 16 suites'
  shapes; docs-honesty-gentar gains an anchor for the new documented path.
- Nothing else — the generator emits to stdout/directory; it does not
  commit to the subject's repo.

## What a runbook will be able to expect

- `gentar subject init demo-subject --repo https://github.com/x/demo`
  emits a TOML that `coordinator ls` accepts and a trigger snippet that
  matches the documented dispatch contract line for line.
- The emitted TOML refuses cleanly (exit 2) before any bench exists when
  its verify probes are left as unfilled stubs — an honest scaffold, not a
  fake-green one.
- A smoke pass: an emitted suite with stubs filled by hand runs green
  against a trivial real checkout.

## Deliberately left out

- Auto-discovering install decisions from the subject repo — that is
  agent work (deferred register), not generator work.
- Any change to the three-move contract itself — the generator implements
  it, does not redesign it.
