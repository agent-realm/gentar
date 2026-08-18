"""Scenario registry. Phase 1 scenarios are Python callables; phase 2
replaces this with the TOML schema + oracle runner (same registry shape).

A scenario receives (bench, run_id, spans) and drives the bench. Its
return value is the verdict summary; raising fails the run.
"""

from collections.abc import Callable

from gentar.benchhost import BenchHost
from gentar.spans import Spans

ScenarioFn = Callable[[BenchHost, str, Spans], str]

REGISTRY: dict[str, ScenarioFn] = {}


def scenario(name: str) -> Callable[[ScenarioFn], ScenarioFn]:
    def register(fn: ScenarioFn) -> ScenarioFn:
        REGISTRY[name] = fn
        return fn
    return register


@scenario("smoke")
def smoke(bench: BenchHost, run_id: str, spans: Spans) -> str:
    """Phase-1 acceptance: create a shell sandbox, exec, destroy."""
    sandbox = run_id
    bench.create(sandbox, agent="shell")
    spans.emit(run_id, "bench.create", attrs={"sandbox": sandbox, "agent": "shell"})

    code, out = bench.exec(sandbox, "uname -a")
    spans.emit(
        run_id, "bench.exec",
        attrs={"sandbox": sandbox, "command": "uname -a", "exit_code": str(code)},
        body=out.strip(),
    )
    if code != 0 or "Linux" not in out:
        raise AssertionError(f"uname -a failed or unexpected: rc={code} out={out!r}")

    return f"smoke ok: {out.strip()}"
