---
node: /s2-arena-portability/b1-second-host-all
scenario: /s2-arena-portability @ 674ef7e
runbooks:
  - /s2-arena-portability/r1-second-host-gate @ 0420d06, run RUN-2026-09-02-02_39.md
  - /s2-arena-portability/r2-spans-join @ 626e37b, run RUN-2026-09-02-02_52.md
blessed-by: auto
waivers:
  - name: compose-secrets-warning
    words: "pilot — 'Waive' at the s2 gate, 2026-09-02"
---

# b1-second-host-all — the arena runs on a second Docker host

Both runbooks green: all six gate suites exit 0 from this Mac (OrbStack)
driving the same bench-host VM 142 over SSH (r1), and spans from the
second-host run land in that host's own ClickHouse with the harness↔agent
join holding — the README quickstart SQL executing verbatim (r2).

Branched from the scenario at `674ef7e`; runbook branches merged as real
merge commits (`4bfa98c`, `be2875a`).

## Tree parking (merge resolution, documented)

Both runbook branches carry their instrument at `plato/RUNBOOK.md`;
merged into one tree that path collides. Resolution: each parked at
`plato/runbooks/<rM>-<slug>.md` (content byte-identical to its branch's
`plato/RUNBOOK.md`). Runbook branches untouched — the grammar lives
there.

## Runs covered

| runbook | run | verdict |
|---|---|---|
| r1-second-host-gate @ 0420d06 | RUN-2026-09-02-02_39 | PASS WITH FINDINGS (waived) |
| r2-spans-join @ 626e37b | RUN-2026-09-02-02_52 | PASS |

Superseded history carried by the merges: RUN-2026-09-02-02_37 (r2 FAIL
pre-steer — runner stripped the `gentar-` prefix from the run id; pilot
steer `626e37b` fixed the capture, added the bounded export-settle wait
and the compose-config port check; steered re-run green).

One waiver: r1's `compose-secrets-warning` — OrbStack's compose ignores
long-syntax secrets uid/gid/mode; cosmetic (key mounts, suites green).
Waived by the pilot at the s2 gate, 2026-09-02, recorded in
RUN-2026-09-02-02_39.md (`waived-by`) and on the r1 branch (`1641a64`).

Autonomy dial is `auto-rc`; the RC gate itself lives in drill.md and
requires the loop `version` field — currently empty, a pilot act.
