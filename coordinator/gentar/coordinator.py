"""Run loop: one scenario, one sandbox lifetime, verdict from reality.
Every run emits run.start / bench.* / run.end spans; exit code is the
verdict (the whole CI contract). Dispatches Python builtins (smoke) and
TOML scenarios (oracle runner)."""

from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.oracle import run_oracle
from gentar.scenarios import REGISTRY, known_names
from gentar.spans import Spans, new_run_id
from gentar.toml_scenario import load_dir


class RunError(RuntimeError):
    pass


def _resolve(name: str, cfg: Config):
    if name in REGISTRY:
        return REGISTRY[name]
    for d in cfg.scenarios_dirs:
        tomls = load_dir(d)
        if name in tomls:
            scenario = tomls[name]
            return lambda bench, run_id, spans: run_oracle(
                scenario, bench, run_id, spans, cfg)
    raise RunError(f"unknown scenario {name!r}; known: {', '.join(known_names(cfg))}")


def run(name: str, cfg: Config | None = None) -> int:
    cfg = cfg or Config()
    fn = _resolve(name, cfg)

    run_id = new_run_id(cfg.name_prefix)
    bench = BenchHost(cfg)
    sandbox = run_id
    spans = Spans(cfg)
    spans.ensure_schema()
    spans.emit(run_id, "run.start", attrs={"scenario": name, "bench_host": cfg.bench_host})

    verdict = 0
    try:
        summary = fn(bench, run_id, spans)
        print(summary)
        spans.emit(run_id, "run.end", attrs={"scenario": name, "verdict": "pass"})
    except Exception as exc:
        verdict = 1
        print(f"FAIL [{name}]: {exc}")
        spans.emit(run_id, "run.end", attrs={"scenario": name, "verdict": "fail"},
                   body=str(exc)[:2000])
    finally:
        # The scenario owns a sandbox named run_id; rm is idempotent and
        # warns instead of raising so teardown never masks the verdict.
        bench.rm(sandbox)

    return verdict
