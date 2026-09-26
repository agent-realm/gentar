# 07 — rates and soft checks

**Shows:** judging a judged suite *over several runs*, and asking the judge
about the end state without letting it decide the verdict. It is example
06's goal pilot with two additions.

**Introduces:**

- `[semantic] runs` / `pass_rate_min` — the suite runs `runs` times, each
  on a fresh bench; exit `0` iff `passes / runs >= pass_rate_min`, exactly
  (2 of 3 is `0.66`, not `0.67`). A refusal is exit `2` at once; it stops
  early once the minimum is out of reach. Judged suites only — a
  deterministic suite must pass every time.
- `[[verify.judge]]` — a yes/no question about the **final** screen, asked
  only after reality passed. **Reported only**: pass / fail / undecided /
  unavailable in the report's "Soft judgments" section; a run whose soft
  check is not a clear yes still passes, marked "judge-flagged". It never
  decides, and never rescues.

Judge caps are per run: `runs` runs may spend up to `runs` times
`[judge] max_calls` / `max_input_tokens`.

## Run it

```bash
with-secret TYPESAFE_API_KEY=<your key reference> -- gentar/run.sh example-rates
```

**Pass:** `semantic rate of example-rates: 3/3 passed (1.00; needs 0.66) — PASS`,
and each run's report shows the soft check.

Next: [08 — a full subject](../08-full-subject/README.md).
