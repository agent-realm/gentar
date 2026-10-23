# Guide — Pick a bench tier

**You want:** the right kind of disposable machine for a suite.

A scenario selects a tier with `bench = "<tier>"` under `[scenario]`.
Without it, the install default applies (`GENTAR_BENCH_KIND`, which is
`sbx`).

## For 1.0, the tier is `sbx`

`sbx` is the one supported tier: a microVM with its own kernel and its
own Docker daemon, so containers a suite starts are born inside the
bench, provably not on the host. It is the only tier in the engine's CI
gate.

The other three are **experimental**. They stay in the engine, but each
has a known defect that keeps it out of 1.0:

| Tier | Bench | Known defect |
|---|---|---|
| `tart` | a macOS VM cloned from a template on Apple hardware | the bench's workspace is created only when a subject is pushed into it, so a subjectless suite's steps get a `$WORKSPACE_DIR` that does not exist |
| `osb` | a plain container under an OpenSandbox server, driven over HTTP and WebSocket | gentar's local pty bridge gives up on a session that sends nothing for 30 seconds, so a driver turn that waits longer on a silent screen loses its terminal; and a driver scenario that forwards env (`credentials` or `pass_env`) is refused (exit 2), because this tier types its pty command |
| `daytona` | a Daytona cloud sandbox | a sandbox whose ssh token cannot be minted after Daytona created it is never deleted: teardown knows only sandboxes that got their token |

Use one only when the suite truly needs it and you accept its defect.
Start with `sbx`.

## Set it up

The setup for each tier, with every variable, is in the
[bench tiers reference](../reference/bench-tiers.md).

## Check

The engine carries one substrate proof per tier: `smoke` for sbx,
`smoke-macos` for tart, `smoke-osb` for osb and `smoke-daytona` for
daytona. Run the one for your tier:

```bash
bin/arena run smoke-macos     # for example
```

A green substrate proof does not clear the defects above: `smoke-macos`
never writes to its workspace, and `smoke-osb` never opens a pty.
