---
hint: bench-host/tart-tier
confirmed-by: grill 2026-08-31
seed: tart-tier
---

# tart-tier

Capability: TartBenchHost — macOS benches as tart VM clones on macminim,
driven over ssh through the tart host, same interface as sbx; opt-in per
scenario (bench = "tart"). Verified: smoke-macos + first macOS subject suite
green, PRs #19/#20.

Hazards: guest vmnet subnet routed only on the Mac — coordinator must run
with a route to it (VM 142 has none, campus firewall); template rebuild is
manual.
