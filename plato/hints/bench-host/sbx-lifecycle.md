---
hint: bench-host/sbx-lifecycle
confirmed-by: grill 2026-08-31
seed: sbx-linux-tier, bench-host-142
---

# sbx-lifecycle

Capability: full programmatic sbx lifecycle over SSH — create (custom
template, workspace bind-mounts), exec / exec -t (pty), cp, ls --json,
run -d, rm; hard two-way isolation; nested Docker inside each sandbox.
Verified by the smoke suite in the gate.

Hazards:

- young version line (v0.38.0 spiked, 0.39 live): 0.39 introduced a first-run
  setup wizard that hijacked pty sessions (dismissed once via forced tty,
  state persists) — pin and re-verify on upgrades.
- tar-after-create breaks bind mounts (getcwd EPERM) — fixed via per-host
  push_before_create ordering; watch the template-load path on upgrades.
- auth is a Docker account; token rotation policy TBD; PAT re-auth procedure
  exists.
- 10s/call keyring tax closed on VM 142 (headless gnome-keyring) — must be
  redone on any fresh host.
