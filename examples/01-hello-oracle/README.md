# 01 — hello, oracle

**Shows:** the smallest complete suite. One oracle step does something, and
one reality check proves it happened.

**Introduces:** `[oracle].steps` (shell lines run in the bench, each must
exit 0) and `[[verify.files]]` (a file that must exist, optionally
containing a substring). `~` is the bench user's home.

```
gentar/scenarios/example-hello-oracle.toml
```

## Run it

These files are shaped like an adopted repo: copy `gentar/` from this
directory into a repo that already has the kit (see
[the adoption kit](../../subject-template/README.md)), then:

```bash
gentar/dryrun.py            # replay locally in about a second, no bench
gentar/run.sh example-hello-oracle        # for real, on a bench; the exit code is the verdict
```

**Pass:** exit `0` — the step exited 0 and `~/hello-gentar.txt` contains
`hello from gentar`. Break the step's text and the file check fails: exit `1`.

Next: [02 — files and commands](../02-verify-files-and-commands/README.md).
