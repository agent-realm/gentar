# 05 — a judged expect

**Shows:** a turn that waits for a screen by *meaning*, not by regex. The
demo CLI's confirmation says "remove … for good" and "retype the name",
never "delete" or "confirm" — a regex written for one wording breaks on
the next; a judged question does not.

**Introduces:**

- `[scenario] data = "synthetic"` — required for any judged turn. Only a
  scenario that declares its screens invented may send one to the judge;
  anything else is refused (exit 2) before a bench exists.
- `[driver.turns.judge]` — `question` (yes/no about `` `screen` ``),
  `true` / `false` (what counts as each), `p_min` (the probability of yes
  needed), `hold` (on this many consecutive polls, at least 2), `every`
  (seconds between polls).
- **Fixtures:** `gentar/judge-fixtures/example-judged/0/{yes,no}/*.txt` —
  screens the turn must answer yes / no to (3+ each; `plan.py lint`
  requires them). Measure them with the engine's `bin/judge-eval`.

What leaves the arena: only the current screen, scrubbed; the span keeps a
hash and a length, never the text. The judge key (`TYPESAFE_API_KEY`) stays
with the coordinator and never reaches the bench.

## Run it

```bash
with-secret TYPESAFE_API_KEY=<your key reference> -- \
  python3 gentar/.arena/bin/judge-eval gentar/scenarios gentar/judge-fixtures --only example-judged
with-secret TYPESAFE_API_KEY=<your key reference> -- gentar/run.sh example-judged
```

Judged suites run in **phase 2 only** — a pull request never runs one.

**Pass:** the judge says no to the rename screen, holds a yes on the
confirmation, the name is typed, and reality agrees: `beta-sandbox` gone,
`alpha-sandbox` kept.

Next: [06 — a goal pilot](../06-goal-pilot/README.md).
