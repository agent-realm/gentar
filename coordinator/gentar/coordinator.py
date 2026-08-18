"""Run loop: one scenario, one sandbox lifetime, verdict from reality.
Every run emits run.start / bench.* / run.end spans; exit code is the
verdict (the whole CI contract)."""

from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.scenarios import REGISTRY
from gentar.spans import Spans, new_run_id


class RunError(RuntimeError):
    pass


def run(name: str, cfg: Config | None = None) -> int:
    cfg = cfg or Config()
    if name not in REGISTRY:
        raise RunError(f"unknown scenario {name!r}; known: {', '.join(sorted(REGISTRY))}")

    run_id = new_run_id(cfg.name_prefix)
    bench = BenchHost(cfg)
    sandbox = run_id
    spans = Spans(cfg)
    spans.ensure_schema()
    spans.emit(run_id, "run.start", attrs={"scenario": name, "bench_host": cfg.bench_host})

    verdict = 0
    try:
        summary = REGISTRY[name](bench, run_id, spans)
        print(summary)
        spans.emit(run_id, "run.end", attrs={"scenario": name, "verdict": "pass"})
    except Exception as exc:
        verdict = 1
        print(f"FAIL [{name}]: {exc}")
        spans.emit(run_id, "run.end", attrs={"scenario": name, "verdict": "fail"},
                   body=str(exc)[:2000])
    finally:
        # Owns the sandbox it named (smoke creates it inside the scenario);
        # rm is idempotent and warns instead of raising.
        bench.rm(sandbox)

    return verdict
