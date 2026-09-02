---
node: /s4-scaffold-hardened/b1-hardened-all
scenario: /s4-scaffold-hardened @ 8ec6d8f
runbooks:
  - /s4-scaffold-hardened/r1-assert-guard @ bcf86ba, run RUN-2026-09-02-04_09.md
  - /s4-scaffold-hardened/r2-schema-strict @ ad14bd9, run RUN-2026-09-02-04_12.md
  - /s4-scaffold-hardened/r3-init-refuse @ dd80e09, run RUN-2026-09-02-04_15.md
  - /s4-scaffold-hardened/r4-green-settle @ dbaac9f, run RUN-2026-09-02-04_18.md
  - /s4-scaffold-hardened/r5-legacy-sixteen @ 0a7b498, run RUN-2026-09-02-04_20.md
blessed-by: auto
waivers: []
---

# b1-hardened-all — the scaffold stays honest under a bending user

All five runbooks green, no findings, nothing to waive. The six drill
findings the pilot steered in ("fix") each have a proving instrument:

- **fake-green 0/0** (d2, d3) — r1: a suite with its whole verify
  section deleted still LOADS but `run` refuses exit 2 with the
  assert-guard message naming "asserts nothing", before any bench
  exists (bench-host snapshots before/after byte-identical:
  `No sandboxes found.`).
- **fake-green stub bypass** (d2) — r2: a probe key renamed off-schema
  (`substring`) is a named ScenarioError (`unknown key(s) substring in
  verify.commands[0] — legal keys: command, contains`); `ls` and `run`
  both exit 2 clean, zero tracebacks; malformed TOML likewise a named
  error carrying file + decoder position.
- **writes-outside / silent overwrite** (d3) — r3: `subject init --dir`
  on held output exits 2 naming exactly the files it refused (the
  partial-hold case names only the held one); `--force` rewrites
  byte-identical to a fresh emit; stdout mode unbroken.
- **sandbox linger** (d1) — r4: a green run (`oracle ok: 2/2`) on the
  bench-host; its sandbox `gentar-s4-20260902-011709-1a2e1c` was absent
  from `sbx ls` at +10s past process exit — settled before the
  coordinator exited; all three snapshots byte-identical.
- **16 suites load unchanged** — r5: `coordinator ls` prints exactly the
  frozen 18-line sorted list (16 suites + builtins `smoke`,
  `smoke-fail`), exit 0, zero diff.

(off-type TOML tracebacks — the third steer item — ride r2's
malformed-TOML case; the confusing-first-contact dead end is covered by
the unknown-scenario pointer, exercised implicitly by r2's clean exit-2
refusals.)

Branched from the scenario at `8ec6d8f`; runbook branches merged as
real merge commits (`fb8a01e`, `5ce6f06`, `a066146`, `81b0f65`,
`812d23c`).

## Tree parking (merge resolutions, documented)

Same convention as s3's b1-standard-all: every runbook branch carries
its instrument at `plato/RUNBOOK.md`, so each merge parks it at
`plato/runbooks/<rM>-<slug>.md` (content verified byte-identical to its
branch's `plato/RUNBOOK.md`). The s3 BLESSED.md this branch inherited
from the scenario tip described s3's bless; this file replaces it —
s3's record lives on frozen in `plato/runs/` history and the s3
branches, which are never moved.

## Runs covered

| runbook | run | verdict |
|---|---|---|
| r1-assert-guard @ bcf86ba | RUN-2026-09-02-04_09 | PASS |
| r2-schema-strict @ ad14bd9 | RUN-2026-09-02-04_12 | PASS |
| r3-init-refuse @ dd80e09 | RUN-2026-09-02-04_15 | PASS |
| r4-green-settle @ dbaac9f | RUN-2026-09-02-04_18 | PASS |
| r5-legacy-sixteen @ 0a7b498 | RUN-2026-09-02-04_20 | PASS |

No waivers: zero findings across all five runs.

Autonomy dial is `auto-rc`; the RC gate itself lives in drill.md and
requires the loop `version` field — currently empty, a pilot act.
