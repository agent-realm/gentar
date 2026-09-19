---
node: /s7-docs-truth/b1-docs-truth-all
scenario: /s7-docs-truth @ c83dc35
runbooks:
  - /s7-docs-truth/r1-prefix-docs-agree @ 5c7420b, run RUN-2026-09-20-00_49.md
  - /s7-docs-truth/r2-envfile-project-seam @ 731aee5, run RUN-2026-09-20-00_52-r2-envfile.md
  - /s7-docs-truth/r3-reconcile-bindtext @ bd07cd7, run RUN-2026-09-20-01_31-r3-reconcile.md
  - /s7-docs-truth/r4-shadow-recovery @ 99f8b8b, run RUN-2026-09-20-00_50-r4-shadow.md
  - /s7-docs-truth/r5-unchanged-regression @ ea63a22, run RUN-2026-09-20-00_52-r5-regression.md
blessed-by: auto
waivers:
  - name: F1 (r5 runbook log-capture merges stderr into the ls log)
    waived-by: "pilot — 'r5 PASS WITH FINDINGS (F1/F2, both runbook log-capture mechanics — pilot waives both by name so they do not block the bless)' at the s7 gate, steer round 2, 2026-09-20"
  - name: F2 (r5 runbook extraction grep also matched 3 rows of the component table)
    waived-by: "pilot — 'r5 PASS WITH FINDINGS (F1/F2, both runbook log-capture mechanics — pilot waives both by name so they do not block the bless)' at the s7 gate, steer round 2, 2026-09-20"
---

# b1-docs-truth-all — every docs-truth claim green against reality

The s5 drills found the coexistence TEXT untrue in seven places; s7's
fan commit fixed it, and this bless freezes the proof that the fixed
text survives contact with live arenas.

## The tally this bless froze

- r1 (PASS): all seven prefix boundary shapes behave as documented;
  the refusal message states the whole rule (leading letter, digits,
  single dashes, 24-char cap, legal/illegal examples); docs agree on
  flattened text.
- r2 (PASS): the `--env-file` seam reproduced exactly — project name
  follows the flag, the coordinator container follows the literal
  `.env`; sandbox + report stamped arena A's prefix while spans landed
  only in arena B's ClickHouse; no error, no third project.
- r3 (PASS, v2 after pilot docs fix c83dc35): drifted `run` recreates
  the running clickhouse onto the exported port; drifted `exec` does
  not (same container, same port, runs inside); the bind error names
  endpoint and port but neither `.env` nor `GENTAR_`; the corrected
  wording present in README + .env.example, the retired false clause
  absent from both.
- r4 (PASS): knob at a native-held port loses silently on OrbStack
  (healthy container, `docker port` lists the mapping, curl answers
  the foreign server — the documented curl-verify detects it); after a
  bind failure, plain `up -d` leaves the publish inert (container
  healthy, `docker port` empty, curl refused) and `--force-recreate`
  restores it.
- r5 (PASS WITH FINDINGS, both waived): the s7 diff vs the s5 tip
  f976be1 is docs + one ValueError message string (`_PREFIX_RE` and
  `_PREFIX_MAX` byte-identical); 18 suites load (16 TOML + smoke +
  smoke-fail), all 17 README inventory suites present; the quickstart
  block runs green (smoke exit 0, report written, `run.end pass`).

## Steer history kept in the record

- r1 v1 FAIL (wrap-brittle greps, RUN-2026-09-02-14_43) → pilot steer
  round 1 → orphan → v2 PASS.
- r2 v1 FAIL (bare `up -d` started the coordinator's default smoke,
  RUN-2026-09-02-14_44) → pilot steer round 1 → orphan → v2 PASS.
- r3 v1 FAIL (the old "run or exec will recreate" claim falsified on
  its exec half, RUN-2026-09-20-00_51) → pilot fixed the docs at
  c83dc35 → pilot steer round 2 → orphan → v2 PASS against the
  corrected wording.

RC tag intentionally absent: PLATO.md carries no version; tagging is
the pilot's act.
