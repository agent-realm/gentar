---
node: /s5-arena-coexist/b1-coexist-all
scenario: /s5-arena-coexist
blessed-by: "auto (autonomy: auto-rc) after pilot waiver 2026-09-02"
stamp: 2026-09-02-05_30
---

# b1-coexist-all — the blessed merge of /s5-arena-coexist

Steered scenario off `/s2-arena-portability @ 3849dcc`; the pilot's
"fix" steer (2026-09-02) drove the s2 drill findings in as opening
commits (@ aac3e37). This bless freezes the instruments and runs that
proved them.

## Runbooks and runs of record

| runbook | frozen at | run of record | verdict |
|---|---|---|---|
| r1-quickstart-default | `4db3861` | `RUN-2026-09-02-04_13` (run commit `ea6bb49`) | PASS WITH FINDINGS — both findings waived (below) |
| r2-prefix-identity | `091ba1e` | `RUN-2026-09-02-04_14-r2-prefix.md` (run commit `7b0f7d2`) | PASS |
| r3-two-arena-coexist | `15236d3` | `RUN-2026-09-02-04_14-r3-two-arena.md` (run commit `51737d7`) | PASS |

Every runbook has a valid run; every verdict is PASS or PASS WITH
FINDINGS with every finding waived by name.

## Waivers (the pilot's, verbatim record)

- `dashboard-agent-spans-zero` — pilot "Waive both, bless" 2026-09-02.
  The dashboard's "0 runs with agent spans" is the TRUE count: the
  smoke suite sends no OTLP self-report, so zero agent spans is
  correct behavior, not an anomaly.
- `runner-exit-code-capture-glitch` — pilot "Waive both, bless"
  2026-09-02. Test-runner shell noise (zsh `PIPESTATUS` mismatch);
  exit 0 is confirmed by the run's own report artifact. Not product.

Waiver commits: `56dbec6` on the r1 branch.

## What this bless proves

- Fresh quickstart on stock defaults runs green beside a native
  clickhouse-server on 8123, and the host port 18123 answers THE
  ARENA — 8123 keeps answering the native server (no shadow).
- Both host publishes bind 127.0.0.1; the GENTAR_*_HOST_PORT knobs
  still override; the dashboard's host fallback reaches the arena.
- Off-shape GENTAR_NAME_PREFIX values refuse exit 2 naming the shape
  rule (no traceback); a valid prefix shows up in the run_id, the
  sandbox name on the bench-host, and the report filename.
- Two arenas — distinct COMPOSE_PROJECT_NAME, distinct ports, one
  .env each — coexist on one Docker host and one bench-host: spans
  fully separated, `sbx ls` distinguishes their sandboxes by prefix.

## Tree notes

Runbook branches each carry `plato/RUNBOOK.md`; in this merge they
are parked at `plato/runbooks/<rM>-<slug>.md` (the runbook branches
themselves are untouched). r2 and r3 finished within the same minute —
both run records are kept, suffixed by runbook
(`RUN-2026-09-02-04_14-r2-prefix.md` / `-r3-two-arena.md`).
