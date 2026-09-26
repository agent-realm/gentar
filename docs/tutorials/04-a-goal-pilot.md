# Tutorial 4 — A goal pilot

A scripted driver needs a turn for every screen. A **goal pilot** gets a
goal and a **closed set of actions**, and on each poll the judge picks one
of them from what the current screen allows. You will build one, measure
it with fixtures, judge it over several runs, and add a soft check of the
final screen.

The worked example is the engine's `goal-demo`
(`coordinator/scenarios/goal-demo.toml`). It is also laid out as
[`examples/06-goal-pilot/`](../../examples/06-goal-pilot/), and the rate
and the soft check as
[`examples/07-rates-and-soft-checks/`](../../examples/07-rates-and-soft-checks/).

## Prerequisites

[Tutorial 3](03-a-judged-turn.md) done. The same egress rule, key
reference and python requirement apply.

## 1. The goal and the actions

`goal-demo` lists two projects with a `>` cursor on `alpha-sandbox`. The
pilot must delete `beta-sandbox` and leave `alpha-sandbox` alone.

```toml
[scenario]
name = "goal-demo"
agent = "shell"
data = "synthetic"

[driver]
command = 'python3 "$WORKSPACE_DIR/demo-tui.py"'
goal = "Delete the project beta-sandbox. Leave alpha-sandbox untouched. You are done once beta-sandbox is no longer listed."
max_steps = 12        # actions, not polls
p_act = 0.8           # the pick's probability needed ...
every = 2             # ... on two consecutive polls, this many seconds apart
timeout = 240

[[driver.actions]]
id = "select_down"
key = "down"
when = "the > cursor is on a project above the one that must be deleted"

[[driver.actions]]
id = "open_delete"
send = "d"
when = "the project list is shown and the > cursor is on the project that must be deleted"

[[driver.actions]]
id = "type_target"
send = "beta-sandbox"
then = "enter"
when = "a prompt asks to retype the name of beta-sandbox to remove it"

[[driver.actions]]
id = "cancel"
key = "escape"
when = "a removal prompt is open for a project that must NOT be deleted"
```

The rules the schema holds you to:

- **The judge never writes.** Every text the pilot can type is a literal
  `send`. A `key` is a named key (`enter`, `escape`, `up`, `down`,
  `ctrl-c`). `then = "enter"` sends Enter as a separate write.
- `when` is what the judge reads to decide. Write it as the screen
  condition under which the action is right.
- `wait`, `done` and `stuck` are always offered. You cannot declare them.
- A goal pilot has no `[[driver.turns]]`: use one or the other.

## 2. How a step is decided

On every poll:

1. The screen is rendered. If it matches the **danger pattern** anywhere,
   the run aborts, whatever the judge would say.
2. The judge makes **one** Choice over what this screen allows.
3. An action is taken only when the **same** pick reaches `p_act` on two
   consecutive polls.
4. Just before acting, the screen is rendered again. The danger gate
   runs again, and the pick must still be offered. Otherwise nothing is
   sent. With `then = "enter"`, the danger gate also runs once more
   before the Enter.

`wait` waits and `stuck` fails the run. `done` stops driving but **is not
a verdict**: `[[verify.*]]` decides. The pilot also fails on the same
screen and pick three times (a loop), on three low-confidence polls in a
row, on `max_steps`, or on the timeout.

## 3. Approval is explicit and narrow

A real TUI sometimes has to be approved, for example claude-code's
trust-folder dialog. An approving action must be declared and anchored:

```toml
[[driver.actions]]
id = "trust_folder"
key = "enter"
approve = true
on = "Do you trust the files in this folder"     # a regex, matched per line
when = "the trust-folder dialog is shown"
```

- An approving action is offered only while its `on` anchor matches the
  screen **and** the danger pattern does not.
- On an approval screen that no declared anchor matches, **no** approving
  action is offered, and neither is any other action that would answer
  it (`y`, `yes`, Enter).
- One limit: "an approval screen" means one that the driver's approval
  pattern recognises. An approval prompt worded so that the pattern
  misses it is an ordinary screen to the code. Keep Enter-sending actions
  out of scenarios where such a prompt can appear, or anchor an
  `approve = true` action to it.

## 4. Goal fixtures

Each fixture is a screen, filed under the action a correct pilot takes
there:

```
coordinator/scenarios/judge-fixtures/goal-demo/goal/select_down/cursor-on-alpha.txt
coordinator/scenarios/judge-fixtures/goal-demo/goal/open_delete/cursor-on-beta.txt
coordinator/scenarios/judge-fixtures/goal-demo/goal/type_target/beta-prompt.txt
coordinator/scenarios/judge-fixtures/goal-demo/goal/cancel/alpha-prompt.txt
coordinator/scenarios/judge-fixtures/goal-demo/goal/done/beta-removed.txt
```

Include the traps. `cancel/alpha-prompt.txt` is the deletion prompt for
the project that must be kept. The kit's lint requires 3 or more goal
screens covering 2 or more actions, one of them `done`.

```bash
with-secret TYPESAFE_API_KEY=keychain:pilot/typesafe -- bin/judge-eval --only goal-demo --repeat 3
```

You should see each fixture's picks and a summary such as
`goal-demo goal: 6/6 fixtures picked right at p_act 0.8`. `judge-eval`
asks exactly what a run asks: the same instructions, and the same offer
for that screen.

## 5. Judge it over N runs

```toml
[semantic]
runs = 3
pass_rate_min = 0.66
```

The scenario runs 3 times, each on a fresh bench, and passes when
`passes / runs >= pass_rate_min`. The comparison is exact: for 2 of 3,
write `0.66`, not `0.67` (2/3 = 0.667). The rules:

- A refusal ends it at once.
- It stops early once the minimum is out of reach.
- Only judged suites may declare a rate. A deterministic suite must pass
  every time.

## 6. A soft check of the final screen

```toml
[[verify.judge]]
question = "Does `screen` show that beta-sandbox was removed and alpha-sandbox is still listed?"
p_min = 0.9
```

It is asked only after the reality checks passed. It is **reported
only**: *pass*, *fail*, *undecided* or *unavailable*, in the report's
"Soft judgments" section. A run with a soft check that was not a clear
yes still passes, marked "judge-flagged". It can never rescue a failure.

## 7. Run it

```bash
with-secret TYPESAFE_API_KEY=keychain:pilot/typesafe -- bin/arena run goal-demo
```

You should see:

```
semantic run 1/3 of goal-demo
oracle ok: 2/2 assertions passed
...
semantic rate of goal-demo: 3/3 passed (1.00; needs 0.66) — PASS
```

## When it fails

- `goal: no confident action on 3 polls running`: the `when` texts do not
  separate the screens. Make each one a condition on what is visible.
- `goal: loop — … on the same screen three times`: the action does not
  change the screen, or its `when` also matches after it acted.
- `goal: the judge is stuck`: the screen allows none of your actions.
  Add the missing action, for example a `cancel`.
- A rate that fails where you expected a pass: check the arithmetic in
  step 5.

## Next

- [Measure a judge with fixtures](../guides/measure-a-judge-with-fixtures.md)
- [Run policy and releases](../guides/run-policy-and-releases.md): judged
  suites belong in phase 2.
