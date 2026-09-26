# 03 — a scripted driver

**Shows:** testing an *interactive* program the way a person uses it, at a
terminal. The oracle step writes a small setup CLI; the `[driver]` runs it
at a pty and the turns answer its prompts.

**Introduces:** `[driver].command` and `[[driver.turns]]`:

| turn | does |
|---|---|
| `answer` | wait for `prompt` (a regex), then type `send` and Enter |
| `expect` | wait for `pattern` on screen, send nothing |
| `key` | send named keys (`enter`, `escape`, `down`, `up`, `ctrl-c`), optionally after a screen `after` |
| `pick` / `abort` | walk a picker; prove the danger gate fires |

The verdict is still reality's: `result.txt`, not what the CLI printed.

## Run it

These files are shaped like an adopted repo: copy `gentar/` from this
directory into a repo that already has the kit (see
[the adoption kit](../../subject-template/README.md)), then:

```bash
gentar/dryrun.py            # replay locally in about a second, no bench
gentar/run.sh example-scripted        # for real, on a bench; the exit code is the verdict
```

**Pass:** exit `0`: the turns answered both prompts and `result.txt` holds
`example-pilot:installed`. A prompt that never appears fails its turn and
names it.

Next: [04 — credentials](../04-credentials/README.md).
