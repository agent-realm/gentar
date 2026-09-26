# Guide — Measure a judge with fixtures

**You want:** evidence that a judged turn or a goal pilot answers right,
before it gates anything, and a threshold that comes from data rather
than a guess.

## Fixture layouts

| Judged thing | Fixtures | Minimum (kit lint) |
|---|---|---|
| a judged `expect` (turn index N) | `judge-fixtures/<scenario>/<N>/yes/*.txt` and `.../no/*.txt` | 3 yes and 3 no |
| a goal pilot | `judge-fixtures/<scenario>/goal/<expected action>/*.txt` | 3 screens over 2 or more actions, one of them `done` |

`judge-fixtures/` sits next to the scenarios. In the engine that is
`coordinator/scenarios/judge-fixtures/`; in a subject repository it is
`gentar/judge-fixtures/`. A fixture is plain text, the screen as the
judge would see it. It must be **synthetic**, like the scenario.

Write the hard cases:

- **no** screens that look almost like yes: the same prompt for another
  object, a rename instead of a delete, a still-loading screen;
- for goal pilots, the **trap**, meaning the screen where the tempting
  action is wrong.

## Run the measurement

```bash
# engine
with-secret TYPESAFE_API_KEY=<reference> -- bin/judge-eval --only <scenario> --repeat 3

# subject repository (engine staged in gentar/.arena)
with-secret TYPESAFE_API_KEY=<reference> -- python3 gentar/.arena/bin/judge-eval gentar/scenarios gentar/judge-fixtures --repeat 3
```

It needs python 3.11 or newer, for `tomllib`. `--repeat` sends each
fixture that many times. Identical requests do not always get identical
answers, so use 3 or more.

## Read the result

For a judged turn, you get one line per fixture, then:

```
<scenario> turn 0: yes >= 0.99, no <= 0.03 (separated); p_min 0.9 holds; recommended p_min >= 0.08 ...
```

- `separated` means every yes scored above every no. `OVERLAP` means the
  question cannot tell them apart. Narrow the question or add
  `true` / `false` criteria; don't just move the threshold.
- `p_min … holds` means the turn's own threshold keeps every yes in and
  every no out.
- The recommended value is the lowest floor that keeps every no out.
  Choose `p_min` between it and your weakest yes.

For a goal pilot you get each fixture's picks and a summary such as
`6/6 fixtures picked right at p_act 0.8`. A fixture counts only when the
expected action wins at `p_act` or above on **every** repeat.

**Exit codes:** `0` means every fixture was judged right, `1` means at
least one was wrong, `2` means a usage problem, a refused judge (the
scenario is not synthetic, or there is no key), or a judge that did not
answer.

## Rates over N runs

`[semantic] runs` and `pass_rate_min` judge a whole scenario over fresh
benches. The rule is exactly `passes / runs >= pass_rate_min`:

| You mean | Write |
|---|---|
| every run | `1.0` |
| 4 of 5 | `0.8` |
| 2 of 3 | `0.66` (2/3 = 0.667, so `0.67` would require 3 of 3) |

Judge caps (`[judge] max_calls`, `max_input_tokens`) apply **per run**,
so N runs may spend up to N times the caps (N is at most 20).

## Check

Re-run `judge-eval` whenever you change a question, a `when` text or a
fixture, and whenever the judge model changes. Thresholds tuned on one
model version do not carry over.
