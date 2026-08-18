"""Scenario registry. Python builtins (arena self-tests) + TOML
scenarios discovered from the configured dirs.

A scenario receives (bench, run_id, spans, subject) and drives the
bench. Its return value is the verdict summary; raising fails the run.
"""

from collections.abc import Callable

from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.spans import Spans
from gentar.toml_scenario import load_dir

ScenarioFn = Callable[..., str]

REGISTRY: dict[str, ScenarioFn] = {}


def known_names(cfg: Config) -> list[str]:
    names = list(REGISTRY)
    for d in cfg.scenarios_dirs:
        names.extend(load_dir(d))
    return sorted(set(names))


def scenario(name: str) -> Callable[[ScenarioFn], ScenarioFn]:
    def register(fn: ScenarioFn) -> ScenarioFn:
        REGISTRY[name] = fn
        return fn
    return register


@scenario("smoke")
def smoke(bench: BenchHost, run_id: str, spans: Spans,
          subject: str = "arena", report=None) -> str:
    """Arena self-test: create a shell sandbox, exec, destroy."""
    spans.emit(subject, run_id, "smoke", "bench.create",
               attrs={"sandbox": run_id, "agent": "shell"})
    bench.create(run_id, agent="shell")

    code, out = bench.exec(run_id, "uname -a")
    spans.emit(
        subject, run_id, "smoke", "bench.exec",
        attrs={"sandbox": run_id, "command": "uname -a", "exit_code": str(code)},
        detail=out.strip(),
    )
    if code != 0 or "Linux" not in out:
        raise AssertionError(f"uname -a failed or unexpected: rc={code} out={out!r}")

    return f"smoke ok: {out.strip()}"


@scenario("smoke-fail")
def smoke_fail(bench: BenchHost, run_id: str, spans: Spans,
               subject: str = "arena", report=None) -> str:
    """Negative test for the verdict machinery itself: a bench command
    fails → the run must FAIL with exit 1, emit run.end(fail), and still
    tear the sandbox down."""
    spans.emit(subject, run_id, "smoke-fail", "bench.create",
               attrs={"sandbox": run_id, "agent": "shell"})
    bench.create(run_id, agent="shell")
    rc, out = bench.exec(run_id, "exit 3")
    spans.emit(subject, run_id, "smoke-fail", "bench.exec",
               attrs={"exit_code": str(rc)})
    if rc == 0:
        raise AssertionError("unreachable: exec should have failed")
    raise AssertionError(f"intentional failure: bench command exited {rc}")
