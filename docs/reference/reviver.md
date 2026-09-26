# Reviver

What every run's report contains, and how it closes the fix loop.

A test runner that only says "fail" makes a human go read logs. gentar
writes, on **every** terminal outcome — pass, fail, and refusal alike —
a markdown report at `out/report-<run_id>.md`
(`coordinator/gentar/report.py`). It contains:

- a header table: run id, verdict and exit code, subject, bench agent and
  template, the credential **names** the run required, sandbox, timestamps;
- **a reproduce command** — the exact invocation that re-runs this suite;
- **every step**, in order, with its exit code and a tail of its output;
- **every assertion**, pass or fail, with what it checked and what it
  actually saw;
- **the pty transcript** when a driver ran — the evidence behind an
  agent-in-the-loop verdict;
- the summary line.

That file is the deliverable of a failing run. Feed it to a coding agent
and it has everything it needs to act: what ran, what it printed, which
assertion disagreed with reality, and how to run it again. Feed it to a
human and they skip the log archaeology. The fix loop closes without
anyone re-deriving the failure.

Try it in one command. `smoke-fail` is the built-in sabotage probe — it
runs a bench command that exits 3, on purpose, to prove the verdict
machinery detects failure at all:

```bash
bin/arena run smoke-fail      # exits 1
cat out/report-*.md
```

Two rules make the reports safe to pass around:

- **Names, never values.** A run report and a span carry the *names* of
  the environment variables a run required. A credential value must never
  reach a report, a span, or a log line.
- **A report never changes a verdict.** Writing it is best-effort in a
  `finally` block; a report that fails to write warns and the exit code
  stands.

Reports are also what the adoption kit wires by default — a subject's own
arena lands them in its repo under `gentar/reports/`.
