# Bench tier setup

Setting up each bench tier beyond the default sbx microVM: tart, osb and daytona.

The default `sbx` tier needs only the Quickstart. The other three need
something the CI gate runner does not have, so they are documented rather
than gated.

**None of the three is supported for 1.0.** Each is experimental, with a
known defect, listed per tier below and in the
[bench tiers guide](../guides/bench-tiers.md).

## `tart` — macOS benches

**Experimental.** A bench's workspace directory is created only when a
subject is pushed into it (`TartBenchHost.push_dir`), so a subjectless
suite's steps get a `$WORKSPACE_DIR` that does not exist.

Benches are clones of a local template VM (`gentar-bench-macos-v1`:
sshd on, the coordinator's public key authorized, agent CLIs on PATH via
the guest's `~/.zshenv`). The Mac runs the tart CLI; guests are reached by
ssh *through* that Mac, because the guest's vmnet subnet is routed only
there. So the coordinator must run somewhere with a route to the Mac —
typically a container on the Mac itself.

```bash
docker build -t gentar-coordinator coordinator/
docker run --rm \
  -v "$HOME/.ssh/id_ed25519:/run/secrets/bench_ssh_key:ro" -v "$PWD/out:/out" \
  -e GENTAR_TART_HOST=host.docker.internal \
  -e GENTAR_BENCH_KEY=/run/secrets/bench_ssh_key \
  -e GENTAR_BENCH_KNOWN_HOSTS=/dev/null \
  gentar-coordinator run smoke-macos
```

Subject suites on this tier need the subject mounted at the coordinator's
subjects root, e.g. `-v <path-to-subject>:/subjects/<name>:ro`. Template
rebuilds are manual: boot the template VM, provision it, `tart stop`.

## `osb` — OpenSandbox containers

**Experimental.** gentar's local pty bridge (`osb_pty_bridge.py`) gives
up on a session that sends nothing for 30 seconds: it closes the WebSocket
and exits 1, so a driver turn that waits longer on a silent screen loses
its terminal. Whether the OpenSandbox server would end such a session too
is not established. A driver scenario that forwards env (`credentials` or
`pass_env`) is refused (exit 2) before any bench exists: this tier types
its pty command, so the values would be echoed into the transcript.

Benches are plain Linux containers under an OpenSandbox server: `create`
maps to a sandbox, `exec` to the execd command API (real exit codes),
`push_dir` to a tarball through the files API, and the pty driver reaches
execd's PTY WebSocket through a small local bridge
(`coordinator/gentar/osb_pty_bridge.py`). No SSH anywhere. The server ships
as an optional compose profile:

```bash
docker compose --profile osb up -d osb-server
docker compose --profile osb run --rm \
  -e GENTAR_BENCH_KIND=osb -e GENTAR_OSB_SERVER=http://osb-server:8080 \
  coordinator run smoke-osb
```

Templates are image refs on the server's Docker daemon
(`GENTAR_OSB_TEMPLATE`, default `python:3.12-slim`). An external server
works too — point `GENTAR_OSB_SERVER` at it.

## `daytona` — cloud sandboxes

**Experimental.** A sandbox whose ssh token cannot be minted after
Daytona created it is never deleted: teardown knows only sandboxes that
got their token. It idle-stops after 15 minutes; delete it by hand.

`create` mints a sandbox from a public image ref through the Daytona SDK;
`exec` and the pty driver go over ssh to Daytona's fixed gateway with a
per-sandbox expiring token as the username — no key file. `push_dir`
streams a tarball over that same session. No infrastructure of your own in
the bench path; it costs Daytona credits per sandbox-hour.

```bash
docker compose run --rm \
  -e GENTAR_DAYTONA_API_KEY="$DAYTONA_API_KEY" \
  coordinator run smoke-daytona
```

Images need a tag or digest — Daytona rejects `latest`. The API key is
**coordinator-scoped and never a scenario credential**: declared
credential values travel into the bench, and the key that mints sandboxes
must not live inside one. The ssh tokens expire by design, so a leaked one
is short-lived.
