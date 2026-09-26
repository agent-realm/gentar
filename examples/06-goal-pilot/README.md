# 06 — a goal pilot

**Shows:** the judge *driving*. Instead of a turn list, the pilot gets a
goal and a closed set of actions, and on each poll picks the one that
advances the goal from the screen in front of it. The trap: pressing `d`
while the cursor is still on `alpha-sandbox` opens *alpha's* deletion
prompt — a correct pilot cancels it.

**Introduces:**

- `[driver] goal`, `max_steps`, `p_act`, `every`, `timeout`.
- `[[driver.actions]]` — `id`, `when` (when the action applies), and
  exactly one of `send` (literal text — the judge never writes) or `key`;
  optional `then = "enter"`. An approving action needs `approve = true`
  and an `on` regex anchoring the one screen it may approve.
- Implicit picks: `wait`, `done` (stops driving — not a verdict), `stuck`.
- An action is taken only when the **same pick** is confident on **two
  polls running**; the danger gate is checked before every poll and again
  before every keypress.
- **Fixtures:** `gentar/judge-fixtures/example-goal/goal/<expected action>/*.txt`
  — each screen, filed under the action a correct pilot takes there
  (3+ screens over 2+ actions, including `done`).

## Run it

```bash
with-secret TYPESAFE_API_KEY=<your key reference> -- \
  python3 gentar/.arena/bin/judge-eval gentar/scenarios gentar/judge-fixtures --only example-goal
with-secret TYPESAFE_API_KEY=<your key reference> -- gentar/run.sh example-goal
```

**Pass:** `select_down → open_delete → type_target → done`, then reality:
`beta-sandbox` gone, `alpha-sandbox` untouched.

Next: [07 — rates and soft checks](../07-rates-and-soft-checks/README.md).
