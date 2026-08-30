# paths — fan from snapshot 1

Enumerated from `plato/root` @ 9f2ee5a (`settle: snapshot 1`). Each surviving
path commits to a mechanism, a seed subset, and the hints it leans on.

## Constraint read first

Three of the five ideals — i1 parallel-matrix, i2 real-agent-runs,
i5 macos-parity — sit wholly inside the deferral register (multi-bench
matrices, real-agent runs, macOS CI leg). The engine does not re-raise
deferred topics, so no path below attacks them. They enter by the pilot's
steer at the review gate — a steer is the pilot's act and unparks; an engine
proposal is not.

## Surviving paths

### p1 — onboard kernel as subject (attacks i4 subject-coverage)

Mechanism: kernel — the constellation's reference lab-pattern component —
becomes a subject: a `gentar/` directory of decision TOMLs in the kernel repo
plus the ~10-line dispatch trigger; suites oracle-first (no LLM), asserting
kernel's documented quickstart against reality in a bench. Seeds:
gentar-repo, scenario-toml, sbx-linux-tier, bench-host-142. Hints:
subjects/mounted-checkouts, ci/forge-agnostic-tiers.

### p2 — arena portability proof (attacks i3 substrate-honesty)

Mechanism: run the whole arena — compose stack + gate suites — on a second
Docker host that is not the CI runner (a laptop / OrbStack-class host),
driving the same bench-host VM 142 over SSH; fix whatever honest portability
gaps surface (paths, env, port discipline). "Runs anywhere Docker runs"
becomes an executed claim, not prose. Seeds: compose-arena, bench-host-142,
telemetry-spans. Hints: bench-host/sbx-lifecycle, ci/forge-agnostic-tiers.

### p3 — subject scaffold generator (attacks i4 subject-coverage)

Mechanism: a generator in the coordinator (`gentar subject init`) that emits a
working scenario TOML skeleton + the trigger workflow snippet from a subject's
name and repo URL — collapsing the three documented moves toward one, making
"any component becomes a subject" mechanical. Seeds: gentar-repo,
scenario-toml. Hints: ci/forge-agnostic-tiers, subjects/mounted-checkouts.

## Struck (recorded, never silent)

- **p4 docs-honesty-deepen** — extends an existing instrument to new anchors;
  no mechanism or material differs from what the docs-honesty suites already
  are. An instrument upgrade, not a path.
- **p5 deferred-ideal attacks (parallel-matrix / real-agent-runs /
  macos-parity)** — their topics sit in the deferral register; proposing them
  is re-raising. Entry is the pilot's steer at the gate.
