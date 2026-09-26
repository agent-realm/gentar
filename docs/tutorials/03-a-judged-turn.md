# Tutorial 3 — A judged turn

A regex `expect` breaks the day a screen is reworded. You will replace
one with a **judged** `expect`: a narrow yes/no question about the
screen, answered by a typed judge ([TypeSafe](https://docs.typesafe.ai),
model pinned to `jev-1.13.0`) with a calibrated probability. You will
also measure the question against fixture screens before trusting it.

The worked example is the engine's `semantic-demo`
(`coordinator/scenarios/semantic-demo.toml`), also laid out as
[`examples/05-judged-expect/`](../../examples/05-judged-expect/).

## Prerequisites

- [Tutorial 1](01-first-run.md) done.
- **A TypeSafe key, stored as a reference.** You never paste it, print it
  or write it down. Store it once with `with-secret --store typesafe`: it
  prompts for the key and stores it as `keychain:pilot/typesafe`. Then
  lend it per command as
  `with-secret TYPESAFE_API_KEY=keychain:pilot/typesafe -- <command>`. If
  the key is already stored under another reference, use that reference
  wherever this tutorial says `keychain:pilot/typesafe`.
- **python 3.11+**, for `bin/judge-eval`.
  (`with-secret` is the pilot's own tool for lending a keychain secret to one
  command; it is not part of gentar. Anything that sets `TYPESAFE_API_KEY`
  for one command without writing it down works the same way.)

## The rule you are working under

A judged turn sends a screen to an external service, so gentar enforces
the pilot's egress rule in code:

- The scenario must declare `[scenario] data = "synthetic"`: invented
  projects, fake accounts, no real credentials or personal data on
  screen. Otherwise the run is refused with exit 2 before any bench
  exists.
- Only the **current screen** is sent: ANSI and box drawing stripped, the
  last 40 content rows, scrubbed of every declared secret. Never the
  transcript, history or files.
- The `judge.call` span records a sha256 and the length of what was
  sent, the question, P(yes), the model that answered, tokens and
  latency. **Never the screen text.**
- The key belongs to the coordinator only. It is never forwarded to a
  bench, and the loader refuses `TYPESAFE_API_KEY` in `credentials` or
  `pass_env`.

## 1. Start from the brittle version

Say the subject's TUI asks for confirmation before deleting a project. A
regex turn would be:

```toml
[[driver.turns]]
type = "expect"
pattern = "Delete project .* confirm"
```

`semantic-demo`'s screen says instead:

```
 You are about to remove "beta-sandbox" and its 3 files for good.
 Retype the project's name to go ahead, or leave it empty to back out:
```

Neither "delete" nor "confirm" appears, and the next release may reword
it again.

## 2. Make it a judged turn

```toml
[scenario]
name = "semantic-demo"
agent = "shell"
data = "synthetic"

[[driver.turns]]
type = "expect"
timeout = 60
[driver.turns.judge]
question = "Does `screen` ask the user to confirm permanently deleting the project named beta-sandbox?"
true = "the screen asks for confirmation to delete or remove beta-sandbox"
false = "anything else: a rename, another project, a list, or still loading"
p_min = 0.9
hold = 2
every = 2
```

What each key does:

- `question` is one narrow yes/no question. Refer to the screen as
  `` `screen` ``. Name the exact thing, so that "the same prompt for
  another project" is a no.
- `true` / `false` say what counts as each answer.
- `p_min` is the P(yes) needed, in (0.5, 1].
- `hold` is how many **consecutive** polls must reach `p_min`, 2 or more.
  Identical requests do not always get identical answers, so a single
  yes never passes a turn.
- `every` is the number of seconds between polls. `timeout` bounds the
  turn.

On each poll the turn renders the screen and checks the danger gate
*first*, then asks the judge. It never presses anything. On a timeout
the turn fails and names the last P(yes) as "a clear no" (at or below
`p_max_no`, default 0.2) or "undecided".

## 3. Write fixtures

Fixtures are screens with a known answer, and they are what tells you
the question works. For turn index 0 of `semantic-demo`:

```
coordinator/scenarios/judge-fixtures/semantic-demo/0/yes/*.txt
coordinator/scenarios/judge-fixtures/semantic-demo/0/no/*.txt
```

Write at least 3 of each. Make the **no** screens hard: the rename
prompt, the same deletion wording for the *other* project, and the plain
list. In a subject repository they live under
`gentar/judge-fixtures/<scenario>/<turn>/{yes,no}/`, and the kit's lint
requires 3 or more of each.

## 4. Measure

```bash
with-secret TYPESAFE_API_KEY=keychain:pilot/typesafe -- bin/judge-eval --only semantic-demo --repeat 3
```

(From a subject repository:
`with-secret TYPESAFE_API_KEY=<ref> -- python3 gentar/.arena/bin/judge-eval gentar/scenarios gentar/judge-fixtures`.)

You should see one line per fixture, then a summary:

```
  semantic-demo turn 0 yes ok  P(yes)=0.99, 0.99, 0.99  demo-actual.txt
  semantic-demo turn 0 no  ok  P(yes)=0.02, 0.02, 0.01  other-project.txt
semantic-demo turn 0: yes >= 0.99, no <= 0.03 (separated); p_min 0.9 holds; recommended p_min >= 0.08 ...
```

Exit 1 means a fixture was judged wrong at the turn's `p_min`. Exit 2
means a usage problem, or a judge that did not answer. See
[Measure a judge with fixtures](../guides/measure-a-judge-with-fixtures.md).

## 5. Run it

```bash
with-secret TYPESAFE_API_KEY=keychain:pilot/typesafe -- bin/arena run semantic-demo
```

You should see `oracle ok: 2/2 assertions passed`, exit 0. The judge
decides only *when the driver has seen* the prompt. The verdict still
comes from reality: `beta-sandbox` is gone and `alpha-sandbox` is kept.

To look at the judge's decisions, run with `GENTAR_KEEP_ARENA=1`, then:

```bash
bin/arena sql "SELECT JSONExtractString(attrs,'judge.q.p_yes'), JSONExtractString(attrs,'judge.sent_chars') FROM gentar.spans WHERE step='judge.call' ORDER BY ts_start"
bin/arena down
```

You should see low P(yes) on the rename screen, then two high ones on the
confirmation: the held yes.

## When it fails

- `judge guard: … does not declare [scenario] data = "synthetic"`, exit 2:
  declare it, but only if the scenario truly shows no real data.
- `judge guard: … TYPESAFE_API_KEY is not set`, exit 2: run under
  `with-secret`.
- `judge never held yes … (a clear no …)`: the question does not match the
  screen. Read the question literally, since the judge does, then check it
  with fixtures.
- `(undecided …)`: the screen is ambiguous for the question. Narrow the
  question, or add `true` / `false`.
- In CI, judged suites never run on a pull request: `plan.py` drops them
  and `run.sh` refuses them. They run in phase 2.

## Next

[Tutorial 4 — A goal pilot](04-a-goal-pilot.md).
