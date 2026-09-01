---
node: /s3-subject-scaffold/b1-standard-all
scenario: /s3-subject-scaffold @ d57d918
runbooks:
  - /s3-subject-scaffold/r1-emit @ ff20143, run RUN-2026-08-31-02_17.md
  - /s3-subject-scaffold/r2-stub-refuse @ 394b2de, run RUN-2026-09-02-02_32.md
  - /s3-subject-scaffold/r3-smoke-green @ 1db47ed, run RUN-2026-09-02-02_30.md
blessed-by: auto
waivers:
  - name: neg-control fail path warns on teardown of a never-created sandbox
    words: "pilot — 'Waive' at the s3 bless gate, 2026-09-02"
---

# b1-standard-all — the subject scaffold generator works honestly end to end

All three runbooks green: `gentar subject init` emits a working suite
skeleton (r1), the as-scaffolded suite refuses exit 2 before any bench
exists when verify stubs are unfilled — and the stub guard orders before
subject delivery (r2), and a hand-filled emitted suite runs green against
a trivial real checkout mounted as a subject (r3).

Branched from the scenario at `d57d918`; runbook branches merged as real
merge commits (`6d874c6`, `df5c41b`, `f219040`).

## Tree parking (merge resolutions, documented)

Every runbook branch carries its instrument at `plato/RUNBOOK.md`, so
merging more than one into a single tree collides. Resolution on this
branch: each runbook parked at `plato/runbooks/<rM>-<slug>.md` (content
byte-identical to its branch's `plato/RUNBOOK.md`). The runbook branches
themselves are untouched — the grammar lives there.

`RUN-2026-08-31-02_16.md` collided the same way: r2's and r3's pre-steer
FAIL runs were stamped within the same minute. r2's copy stays at
`plato/runs/RUN-2026-08-31-02_16.md`; r3's is parked at
`plato/runs/r3-smoke-green/` beside its green re-run. Both pre-steer
FAILs are superseded by pilot steers (`394b2de`, `1db47ed`) and green
re-runs; they are kept as history, never silently dropped.

## Runs covered

| runbook | run | verdict |
|---|---|---|
| r1-emit @ ff20143 | RUN-2026-08-31-02_17 | PASS |
| r2-stub-refuse @ 394b2de | RUN-2026-09-02-02_32 | PASS WITH FINDINGS (waived) |
| r3-smoke-green @ 1db47ed | RUN-2026-09-02-02_30 | PASS |

Superseded history on the runbook branches, carried here by the merges:
RUN-2026-08-31-02_14 (r1, incomplete), RUN-2026-08-31-02_16 (r2 FAIL
pre-steer, r3 FAIL pre-steer).

One waiver: the r2 finding "neg-control fail path warns on teardown of a
never-created sandbox" — waived by the pilot at the bless gate, 2026-09-02,
recorded verbatim in RUN-2026-09-02-02_32.md (`waived-by`) and on the r2
branch (`b7f5037`).

Autonomy dial is `auto-rc`; the RC gate itself lives in drill.md and
requires the loop `version` field — currently empty, a pilot act.
