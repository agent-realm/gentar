# Pilot simulator

Driving a real agent at a pty: scripted turns, the danger gate, credentials, judged turns, goal pilots, rates and soft judgments.

Most testing drives software through its API. A pilot simulator drives it
through its **terminal**, as the person would: a real agent CLI at a real
pty on the bench, answering its onboarding dialogs, typing a task,
waiting for the reply.

A scenario's `[driver]` block names the command and a list of **turns**
(`coordinator/gentar/scripted.py`):

| Turn | Does |
|---|---|
| `answer` | wait for a prompt pattern, then type text |
| `expect` | wait for a pattern to appear on screen |
| `pick` | walk a `❯`-cursor picker to a labeled option and select it |
| `key` | send raw key events (`enter`, `escape`, `ctrl-c`), optionally anchored to a screen and paced |
| `abort` | prove the danger gate fires |

`agent-pty-smoke` is the live suite: a real `claude-code` TUI on a bench,
driven through its entire first run — theme picker, declining the
sandbox's inert placeholder API key, the confirm footer, an intermittent
security-notes page, the trust-folder dialog, the bypass-permissions
warning — then given a task, then exited. The verdict is a byte-for-byte
`cmp` of the file it was asked to write. Not the agent's reply. Not the
transcript. The file.

Three mechanics the driver had to learn, all proven live on a bench and
all encoded in the turn schema, because they are the difference between a
script that works and one that is subtly lying:

- **Submission is a separate event.** The TUI paste-guards a trailing
  Enter that arrives in the same write as the text, so every `answer` into
  an input box is followed by its own `key enter` turn — and it must be a
  real `\r`; a `sendline`'s `\n` is ignored.
- **The screen is a diff, not a stream.** The TUI re-sends only changed
  cells and jumps the cursor across unchanged ones, so a single frame
  literally lacks letters still on screen. The driver replays the pty
  stream through a cell model (`_render` in
  `coordinator/gentar/pty_driver.py`, unit-tested in
  `coordinator/tests/test_render.py`) instead of tailing raw bytes.
- **Turns are anchored, not blind.** An Enter waits for its own screen
  (`after = "…"`), because a paced pair races the render and can
  pre-accept the *next* dialog's default. A dialog that appears only
  sometimes is an `optional` turn.

The hard safety rule in the driver is the **danger gate**: if the agent
provokes a prompt asking to run a command matching the destructive-command
pattern, the driver aborts the run rather than approving it. That is not a
documented intention — `scripted-danger` is a gate suite that fails unless
the gate fires before any approval, and it runs on every PR.

**Credentials are injected at run time and never baked.** A scenario
declares the environment variable *names* it needs. Entries are
alternatives, and a list entry is an all-of group:

```toml
credentials = ["ANTHROPIC_API_KEY",
               ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]]
```

The first fully-present group wins and is forwarded whole; nothing outside
it travels, so a stray endpoint variable cannot redirect a key that won on
its own. If no group is complete, the run **refuses with exit 2 before any
bench exists** — a missing credential is a usage error, not a red test, and
a token without its endpoint is half a provider, which never gets to start
a misconfigured bench. Any Anthropic-protocol endpoint works, not just the
first-party one.

The value has to reach the *coordinator* first, and a container inherits
nothing from your shell: `bin/arena` reads the names each scenario
declares and passes them through with `-e NAME`, so exporting them is
enough. Bare `docker compose run` does not — add the same `-e` flags, as
the [CI contract](ci-and-releases.md) does.

## When a turn fails — the failure snapshot

A failed turn, the final wait for EOF timing out, the danger gate or a
failed goal pilot all end the driver before `[verify]` runs. Before the
session is closed, the engine captures into the report:

- the **last screen**, rendered from the cell model the turns read;
- the **raw tail** of the pty byte stream, control bytes shown as `\xNN`;
- the **process tree** inside the bench (`ps … --forest`);
- the output of each `[on_failure]` command, run on the bench.

```toml
[on_failure]
commands = ["devbox info", { command = "ls -la ~/.claude", timeout = 20 }]
```

A command is a string or `{ command, timeout }` (1..600 s, default 60,
as for verify). `[on_failure]` needs a `[driver]`. Every part is scrubbed
like the rest of the report, and a part that cannot be read says why
instead of hiding the failure. It is never a verdict.

## Semantic turns — a judged `expect`

A regex `expect` breaks the day a screen is reworded. A **judged** `expect`
asks a narrow yes/no question about the screen instead, and a typed judge
([TypeSafe](https://docs.typesafe.ai), model pinned to `jev-1.13.0`) answers
with a calibrated probability:

```toml
[scenario]
data = "synthetic"                 # required: see "what may leave" below

[[driver.turns]]
type = "expect"
timeout = 60
[driver.turns.judge]
question = "Does `screen` ask the user to confirm permanently deleting the project named beta-sandbox?"
true = "the screen asks for confirmation to delete or remove beta-sandbox"
false = "anything else: a rename, another project, a list, or still loading"
p_min = 0.9        # P(yes) needed ...
hold = 2           # ... on this many consecutive polls
every = 2          # seconds between polls
```

The turn polls the rendered screen until the judge says yes with
`P(yes) >= p_min` on `hold` consecutive polls. Identical requests do not
always get identical answers, so a single yes is not enough. It never
presses anything, and the danger gate is checked on every poll before the
judge is asked. A timeout fails the turn and names the last P(yes) as a
clear no or undecided. **The verdict is still reality's:** a judged turn
only decides when the driver has seen what it waits for, and
`[[verify.*]]` decides pass or fail.

**What may leave the arena** (the pilot's rule, enforced in code):

- only for a scenario that declares `data = "synthetic"`. Anything else
  with a judged turn is refused, exit 2, before any bench exists;
- only the current screen, with ANSI and box drawing stripped and the last
  `[judge] lines` rows kept (default 40), scrubbed by the same redactor as
  the export. Never the transcript, history or files;
- the `judge.call` span records the sha256 and length of what was sent,
  the question, P(yes), the model that answered, and the tokens and
  latency. Never the screen text.

**The key** is `TYPESAFE_API_KEY`, and it belongs to the **coordinator
only**: it is never forwarded to a bench. The loader refuses it in
`credentials` or `pass_env`. Without it, a judged scenario is refused
(exit 2), and a kit sweep skips it by name. Lend it per run:
`with-secret TYPESAFE_API_KEY=keychain:typesafe -- bin/arena run semantic-demo`.
`[judge] max_calls` (default 200) and `max_input_tokens` (default 500k)
cap a run.

**Fixtures measure a question before it gates anything.** A judged turn's
fixture screens live at
`judge-fixtures/<scenario>/<turn-index>/{yes,no}/*.txt`.
`bin/judge-eval` sends each one `--repeat` times and reports the P(yes)
spread per class, whether the turn's `p_min` separates them, and a
recommended floor. It exits 1 on any misjudged fixture. The kit's lint
requires 3+ yes and 3+ no fixtures per judged turn, keeps judged suites out
of phase 1 (a PR never runs one), and requires `data = "synthetic"`.
`semantic-demo` is the engine's own example. Its screen says "remove … for
good" and "retype the name", never "delete" or "confirm", and the trap
fixture (the same wording for the *other* project) scores 0.02.

## Goal pilots — the judge drives toward a goal

A goal pilot gets a **goal** and a **closed set of actions** instead of a
turn list. On each poll the judge picks one action, `wait`, `done` or
`stuck` from what the current screen allows:

```toml
[scenario]
data = "synthetic"

[driver]
command = 'python3 "$WORKSPACE_DIR/demo-tui.py"'
goal = "Delete the project beta-sandbox. Leave alpha-sandbox untouched."
max_steps = 12        # actions, not polls
p_act = 0.8           # the pick's probability needed ...
every = 2             # ... on two polls running (seconds between polls)
timeout = 240

[[driver.actions]]
id = "open_delete"
send = "d"            # literal text; the judge never writes
when = "the project list is shown and the > cursor is on the project that must be deleted"

[[driver.actions]]
id = "trust_folder"   # an approving action: explicit and anchored
key = "enter"
approve = true
on = "Do you trust the files in this folder"
when = "the trust-folder dialog is shown"
```

- **Rules, in code:**
  - Before every poll, a screen matching the danger pattern aborts,
    whatever the judge would say.
  - An action is taken only when the **same** pick reaches `p_act` on two
    consecutive polls.
  - On an approval screen, only a declared `approve = true` action whose
    `on` regex anchors that very screen is offered. No other action that
    would answer it (`y`, `yes`, Enter) is offered, and an approving action
    is never offered off its anchor.
  - The same screen and pick three times is a loop and fails. So does
    `stuck`, three low-confidence polls running, `max_steps`, or the
    timeout.
- **`done` is not a verdict.** It stops driving, and `[[verify.*]]`
  decides.
- **A limit worth knowing:** "an approval screen" means one that the
  driver's approval pattern recognises. An approval prompt worded so the
  pattern misses it is, to the code, an ordinary screen, and any declared
  action may be picked there. The danger gate still applies. So keep
  Enter-sending actions out of scenarios where an unrecognised approval
  prompt can appear, or add an `approve = true` action anchored to it.
- **The same egress rule** applies as for judged turns: synthetic only,
  the scrubbed current screen, and a hash in the span.
- **The goal is in the question, not the screen state,** so screen text
  can't restate it.

**The judge sits behind a backend interface.** A backend declares whether
its probabilities are `calibrated`, and whether its `egress` is
`external` or `in-house`. TypeSafe is calibrated and external, and is the
only backend. An uncalibrated backend is refused wherever a threshold
decides. Whether a backend may see a scenario's screens is decided in one
function (`judge.egress_allowed`). Today that means synthetic only, for
every backend.

**Fixtures:** `judge-fixtures/<scenario>/goal/<expected action>/*.txt`
holds screens and the action a correct pilot takes on each.
`bin/judge-eval` asks exactly what a run asks (the same instructions and
the same offer for that screen) and requires the expected pick at
`p_act`. `goal-demo` is the engine's example: 6 of 6 right, including the
trap (alpha's deletion prompt → `cancel`, 1.00). Live, it went
`select_down` (0.93), `open_delete`, `type_target`, `done` (1.00), in 8
judge calls.

## Rates and soft judgments

A judged suite can be judged **over N runs**, each on a fresh bench:

```toml
[semantic]
runs = 3              # 1..20
pass_rate_min = 0.67  # passes/runs needed for exit 0
```

- A refusal (exit 2) ends it at once, since it would refuse every time.
- It **stops early** once the minimum is out of reach: further runs would
  spend judge calls on a known verdict.
- Every run writes its own report, and a `semantic.rate` span records the
  passes.
- **Only judged suites** may declare a rate. A deterministic suite must
  pass every time, and a rate would only hide its flakes.
- The rule is exactly `passes / runs >= pass_rate_min`: for 2 of 3 write
  `0.66`, not `0.67` (2/3 = 0.667).
- Judge caps (`[judge] max_calls`, `max_input_tokens`) are **per run**, so
  N runs may spend up to N times the caps, with N ≤ 20.
- A quarantined suite is skipped once. It doesn't "pass" N times.

A **soft judgment** asks a yes/no question about the driver's **final**
screen, after reality has passed:

```toml
[[verify.judge]]
question = "Does `screen` show that beta-sandbox was removed and alpha-sandbox is still listed?"
p_min = 0.9
```

- It is **reported only**: *pass*, *fail*, *undecided* or *unavailable*,
  in the report's "Soft judgments" section and a `judge.soft` span.
- A run with a soft check that isn't a clear yes still passes, marked
  "judge-flagged".
- It never runs after a reality failure, so it can never rescue one.
- It follows the same egress rule as every judged turn.

Today the agent under the pty is `claude-code`, pinned by
`bench-template/VERSION` and baked into the bench template so no run
depends on a registry at test time. The driver itself is agent-agnostic;
adding another CLI is a turn script, not engine work.
