# Examples — smallest to full

Each directory is a working example with its own README: what it shows,
what it introduces, how to run it, and what passing looks like. They are
shaped like an adopted repo — copy an example's `gentar/` into a repo that
has [the adoption kit](../subject-template/README.md).

| # | example | introduces | bench? | key? |
|---|---|---|---|---|
| 01 | [hello-oracle](01-hello-oracle/README.md) | `[oracle].steps`, `[[verify.files]]` | yes (dry-run: no) | — |
| 02 | [verify-files-and-commands](02-verify-files-and-commands/README.md) | `contains`, `[[verify.commands]]` | yes (dry-run: no) | — |
| 03 | [scripted-driver](03-scripted-driver/README.md) | `[driver]`, `answer` / `expect` turns | yes (dry-run: no) | — |
| 04 | [credentials](04-credentials/README.md) | `credentials` alternatives and groups, `template`, `[budget]` | yes | an agent key |
| 05 | [judged-expect](05-judged-expect/README.md) | `data = "synthetic"`, `[driver.turns.judge]`, fixtures | yes | `TYPESAFE_API_KEY` |
| 06 | [goal-pilot](06-goal-pilot/README.md) | `goal`, `[[driver.actions]]`, goal fixtures | yes | `TYPESAFE_API_KEY` |
| 07 | [rates-and-soft-checks](07-rates-and-soft-checks/README.md) | `[semantic]` rates, `[[verify.judge]]` | yes | `TYPESAFE_API_KEY` |
| 08 | [full-subject](08-full-subject/README.md) | `policy.toml`, `hooks.py`, the kit's layout | yes | — |
| 09 | [public-repo-mirror](09-public-repo-mirror/README.md) | `[arena] bench = "mirror"`, `[phase2] evidence`, `[secrets] route` | in the mirror | a routed secret |

"Dry-run: no" means `gentar/dryrun.py` replays it locally without a bench.
Suites with credentials are skipped by the dry-run; judged suites need the
judge and a bench.
