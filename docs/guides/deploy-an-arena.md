# Guide — Deploy an arena

**You want:** a subject repository's own arena running in CI: a
bench-host to create benches on, a self-hosted runner to run the arena,
and the secrets it reads.

For the procedure an agent follows, including what to ask the pilot,
see [`AGENTS.md`](../../AGENTS.md).

## 1. A bench-host

Any Linux machine reachable over SSH.

1. Install the [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)
   CLI `sbx`, and log in once with `sbx login` (device flow; the token
   persists).
2. Create or choose an account that the arena will SSH in as, and
   authorise a key for it. That key becomes the `BENCH_SSH_KEY` secret.
3. **Do not store sbx secrets on it** (`sbx secret set`). sbx's
   credential proxy hands a stored secret to every sandbox, so the
   engine refuses such a host with exit 2 before creating a bench. Set
   `GENTAR_SBX_SECRETS=allow` only for an arena that uses them on
   purpose.

Check: `ssh <user>@<host> sbx ls` works with that key.

## 2. A self-hosted runner

The kit's workflow runs the arena on a runner labelled **`arena`**. A
GitHub-hosted runner cannot reach an internal bench-host.

1. Pick any always-on machine with Docker and network reach to the
   bench-host. It can be the bench-host itself.
2. In the repository: Settings → Actions → Runners → New self-hosted
   runner, then add the label `arena`.
3. On a **public** repository, also set "Require approval for all
   external contributors". The kit never runs a fork's PR on the runner,
   but a fork can add its own workflow aimed at it.

Several repositories can share one runner machine: register one runner
per repository.

## 3. Secrets and variables

| Name | Kind | Needed when |
|---|---|---|
| `BENCH_SSH_KEY` | secret | always: the key that reaches the bench-host |
| `GENTAR_BENCH_HOST` | secret | always: the engine ships no bench-host |
| `GENTAR_BENCH_USER` | secret | always: the account on it |
| `GENTAR_CLONE_KEY` | secret | the **engine** repository is private: a read-only deploy key on it |
| `GENTAR_REPO_URL` | variable | only to point at a fork or mirror of the engine |
| `GENTAR_OTLP_EXPORT`, `GENTAR_OTLP_KEY` | secrets, both or neither | runs should reach a telemetry destination: see [Send telemetry to ClickStack](send-telemetry-to-clickstack.md) |
| `TYPESAFE_API_KEY` | secret | the repository has judged suites (semantic turns, goal pilots, soft checks); unset, they are skipped by name |
| `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` | secret / variable | agent-in-the-loop suites only |
| `GENTAR_CLICKHOUSE_HOST_PORT`, `GENTAR_OTLP_HOST_PORT` | variables | another arena already uses the default ports on the runner machine |

The bench-host values are **secrets, not variables**, because a public
repository's Actions logs are public. Set every secret from a reference,
and never paste a value into a chat, a file or a log. For example, to pipe
a key from your keychain straight into a secret:

```bash
with-secret V=<reference> -- sh -c 'printf %s "$V" | gh secret set NAME -R owner/repo'
```

## 4. Ports, when arenas share a machine

Each arena publishes ClickHouse (default `8123`) and the OTLP receiver
(default `4318`) on its runner machine. A second arena on the same machine
needs its own pair, set as repository variables, for example
`GENTAR_CLICKHOUSE_HOST_PORT=8127` and `GENTAR_OTLP_HOST_PORT=4321`.

## 5. What serialises, and what does not

- **Per subject:** `run.sh` takes a lock named after the subject, so a
  second run of the same repository **waits**, and prints who holds the
  lock. Locks live under `/tmp/gentar-locks`, or under
  `$GENTAR_LOCK_DIR/gentar-locks` if you set `GENTAR_LOCK_DIR`.
- **Not per host:** runs of *different* subjects on one bench-host can
  overlap. That is fine for a bench each; size the host for it.
- **Template builds need a window.** An sbx `template save` blocks the sbx
  daemon for the **whole host** for its duration (tens of minutes for a
  multi-GB template). Benches of every arena on that host stall in
  `sbx create` meanwhile. Announce a window with no arena run in flight
  before building one.

## Check

Open a pull request, push to the default branch, or push the `arena`
keyword tag at a commit. The workflow's plan job says what it will run,
and the bench job runs it. A missing bench-host secret makes the workflow
refuse up front, naming the secret.

Next: [Run policy and releases](run-policy-and-releases.md).
