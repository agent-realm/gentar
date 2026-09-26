# Guide — Pick a bench tier

**You want:** the right kind of disposable machine for a suite.

A scenario selects a tier with `bench = "<tier>"` under `[scenario]`.
Without it, the install default applies (`GENTAR_BENCH_KIND`, which is
`sbx`).

## Which tier do I want?

| If the suite needs | Use | Why |
|---|---|---|
| a Linux machine for almost anything, including starting its own containers | `sbx` (default) | a microVM with its own kernel and its own Docker daemon; containers are born inside the bench, provably not on the host |
| macOS specifically, because the install path differs on darwin/arm64 | `tart` | a macOS VM cloned from a template on Apple hardware |
| a plain container of a given image, reached without SSH | `osb` | an OpenSandbox server, driven over HTTP and WebSocket |
| a bench that no machine of yours has to host | `daytona` | a Daytona cloud sandbox |

Start with `sbx`. Choose another tier only when the suite truly needs
it, since only `sbx` is in the engine's CI gate.

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
