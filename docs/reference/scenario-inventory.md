# Scenario inventory

The engine's own suites, what each proves, and which need a subject or credentials.

22 suites: 20 TOML files in `coordinator/scenarios/`, plus two Python
built-ins (`smoke`, `smoke-fail`). Every verdict comes from reality.
List them live with `bin/arena ls`.

Where a suite names another project, this is what it is: **kommander-playbook**
is a Claude Code configuration playbook, **memhouse** is a ClickHouse-backed
memory service, **claude-playbooks** is the CLI that installs playbooks.

| Suite | Tier | What it proves |
|---|---|---|
| `smoke` | sbx | bench lifecycle: create → exec `uname -a` → span → destroy |
| `smoke-fail` | sbx | the verdict machinery itself: a sabotaged step must produce exit 1 and still tear the bench down |
| `smoke-macos` | tart | Darwin arm64 + the pinned CLI on a Mac bench |
| `smoke-osb` | osb | Linux container bench driven entirely over the OpenSandbox API |
| `smoke-daytona` | daytona | cloud sandbox minted via SDK, driven over ssh with an expiring token |
| `bench-template-verify` | sbx | a bench from `gentar-bench-v1` carries the pinned agent CLI |
| `otlp-selfreport` | sbx | software inside the bench can self-report OTLP spans that join harness spans on `run_id` in one SQL |
| `budget-sim` | sbx | the budget guard refuses an over-cap run (exit 2) |
| `scripted-onboarding` | sbx | pty driver mechanics: answer / pick / expect turns, no LLM |
| `scripted-danger` | sbx | the danger gate fires before any approval |
| `agent-smoke` | sbx | a real `claude-code` does a trivial task headlessly; provider-agnostic credential, refuses without one |
| `agent-pty-smoke` | sbx | **pilot simulation**: a real `claude-code` TUI driven through first-run onboarding and a task; byte-exact file verdict |
| `agent-profile-smoke` | sbx | a real agent running *under* a configuration install pinned to the newest release tag — the ref under test is never its own tool; triple reality verdict |
| `claude-playbooks-install` | sbx | the documented CLI install path, verbatim, 9 reality assertions |
| `claude-playbooks-install-macos` | tart | the same suite on a Mac bench — installers behave identically on darwin/arm64 |
| `kommander-install` | sbx | the README's standalone install path: in-place install, launcher, data dirs, helper |
| `kommander-update` | sbx | upgrade from an old release tag to the checkout's VERSION; data survives `reset --hard` |
| `kommander-task-lock` | sbx | a lock guard's exit contract under a live PID matrix (0 acquired / 2 live / 3 stale) |
| `memhouse-install` | sbx | `npm install -g` from the mounted checkout; schema claims read out of the shipped artifacts |
| `memhouse-house` | sbx | a real service deployed inside the bench's own Docker daemon; verdicts are SQL counts against it |
| `docs-honesty-kommander` | sbx | a README's install *and* uninstall paths run verbatim, drift-guarded |
| `docs-honesty-gentar` | sbx | the repository README's own claims, checked against this repo |
| `driller-white-hat-demo` | sbx (deny-by-default host only) | a white hat driller session against a synthetic CLI with two planted flaws (a world-readable token, a token printed on screen); the verdict is the boundary audit, the findings are reported and ranked over 5 sessions |

The last one is worth a sentence. `docs-honesty-gentar` greps the
[README](../../README.md) for the commands it tells you to run, then proves their targets exist:
`.env.example`, `docker-compose.yml`, `dashboard/generate.py`,
`bench-template/VERSION`, the scenarios named above, the CI job names.
If the README drifts from the repo, the release gate goes red. Docs
honesty is a dimension under test, not an aspiration.
