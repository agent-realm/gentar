# 02 — files and commands

**Shows:** a suite shaped like a real install check: several steps, then
assertions against what is on disk and what a command prints.

**Introduces:**

| check | passes when |
|---|---|
| `[[verify.files]]` with `path` | the file exists |
| `[[verify.files]]` with `path` + `contains` | the file contains the substring |
| `[[verify.commands]]` with `command` | the command exits 0 |
| `[[verify.commands]]` with `command` + `contains` | it exits 0 and its output contains the substring |

Assert against reality: files, processes, command output. Never assert
"the tool said it worked".

## Run it

These files are shaped like an adopted repo: copy `gentar/` from this
directory into a repo that already has the kit (see
[the adoption kit](../../subject-template/README.md)), then:

```bash
gentar/dryrun.py            # replay locally in about a second, no bench
gentar/run.sh example-verify        # for real, on a bench; the exit code is the verdict
```

**Pass:** exit `0` with 4 of 4 assertions passing. The report lists every
step and assertion with its output.

Next: [03 — a scripted driver](../03-scripted-driver/README.md).
