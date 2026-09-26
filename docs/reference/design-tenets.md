# Design tenets and scope map

The rules gentar is built on, and where to find the scope map of what contains what.

## Design tenets

- **Verdicts from reality.** Files, exit codes, processes, SQL, spans,
  screen contents. Never "the software said it worked", and never "the
  agent said it worked". Self-reported telemetry is welcome — it joins
  harness spans on `run_id` — but it is evidence, not a verdict.
- **The bench is the reset.** Every scenario gets a fresh one, and a
  wedged run is discarded rather than repaired.
- **Subjects mount, never bake.** See below.
- **Refuse, don't fail.** A missing credential, an unknown suite name, an
  over-budget run: these are usage errors. They exit 2 before a bench is
  created, so a misconfiguration costs nothing and never masquerades as a
  broken product.
- **Names, never values.** Credentials travel as environment variables
  into a throwaway that dies with the run. Spans and reports carry the
  names a run required.
- **Machinery is pinned, never itself.** When a suite's own tooling
  overlaps the thing under test, the tooling is pinned to a previous
  release. The ref under test is never its own test harness.
- **Nothing between a suite and CI.** `docker compose run` and an exit
  code. No report format, no plugin, no forge feature in the critical
  path.

gentar was born in the [Ultimagent](https://github.com/agent-realm/ultimagent)
constellation, whose components are its first adopters; nothing in the
engine depends on that, and the suites in the [scenario inventory](scenario-inventory.md) that name other projects are
simply the subjects it was proven against.


## Subjects mount, never bake

The one rule worth stating here, because it is what the arena exists to
enforce: **subjects mount, never bake.** Your checkout is staged into the
run at run time and delivered into a fresh bench. No image ever carries
it, so there is no sandbox image to rebuild and no stale copy to test by
accident.

## Scope map

New to the vocabulary, or unsure which machine holds what?
**[`docs/scope-map.md`](../../docs/scope-map.md)** — what contains what, every
relation counted (`1 → 1`, `1 → N`, `N → 1`, `N → M`), and the three
cardinalities people get backwards: a runner is not per-run, a job is not
per-scenario, and a second runner does not give you a second bench-host.
A rendered version with hand-drawn figures sits beside it at
[`docs/scope-map.html`](../../docs/scope-map.html).
