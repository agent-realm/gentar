---
seed: sbx-linux-tier
confirmed-by: grill 2026-08-31
---

# sbx-linux-tier

Linux benches are sbx sandboxes (Docker Sandboxes) spawned by the coordinator
over SSH on a bench-host: per-run microVM, own Docker daemon each, hard
two-way isolation. Lifecycle used: create / exec -t (pty) / exec / rm behind
the two-tier BenchHost interface. Spiked live on arf (decision #6,
2026-08-18); auth = device flow once per host, token persists; PAT re-auth
exists.
