"""Run loop: one scenario, one sandbox lifetime, verdict from reality.

The run itself is a TWO-ROW scenario span (gauntlet policy, ported):
a `running` row opens it, the terminal row carries status/duration and
the full provenance attrs — stamped on BOTH rows, because the terminal
row is the one a duration-comparison query selects. Exit code is the
verdict: 0 pass · 1 fail · 2 usage/config refusal. Dispatches Python
builtins (smoke) and TOML scenarios (oracle runner)."""

import os
import time

from gentar.benchhost import BenchHost, make_bench
from gentar.config import Config
from gentar.oracle import run_oracle
from gentar.provenance import run_attrs
from gentar.report import RunReport
from gentar.scenarios import REGISTRY, known_names
from gentar.spans import Spans, new_run_id
from gentar.toml_scenario import ScenarioError, TomlScenario, load_dir

# Subject label for subjectless builtins/scenarios: the arena itself.
ARENA_SUBJECT = "arena"


class RunError(RuntimeError):
    pass


def _write_report(report: RunReport, cfg: Config) -> None:
    """Best-effort, like all artifacts: a report failure must never
    change the verdict. Empty report_dir disables writing."""
    if not cfg.report_dir:
        return
    try:
        path = report.write(cfg.report_dir)
        print(f"report: {path}")
    except Exception as exc:
        print(f"warn: report write failed (non-fatal): {exc}")


def _resolve(name: str, cfg: Config) -> tuple:
    """-> (callable(bench, run_id, spans) -> summary, TomlScenario | None)"""
    if name in REGISTRY:
        return REGISTRY[name], None
    for d in cfg.scenarios_dirs:
        tomls = load_dir(d)
        if name in tomls:
            scenario = tomls[name]
            return (lambda bench, run_id, spans, subject="arena",
                    report=None: run_oracle(
                scenario, bench, run_id, spans, cfg, subject=subject,
                report=report)), scenario
    raise RunError(f"unknown scenario {name!r}; known: {', '.join(known_names(cfg))}")


def _spent_so_far(spans: Spans) -> int:
    """Units already burned by past runs, accumulated from spans.
    Best-effort like all telemetry: unreadable == 0."""
    if spans.client is None:
        return 0
    try:
        result = spans.client.query(
            "SELECT toUInt64OrZero(JSONExtractString(attrs, 'tokens')) "
            "FROM {db}.spans WHERE step='budget.spend'".format(
                db=spans.cfg.clickhouse_db))
        return sum(int(v) for v in result.result_columns[0])
    except Exception:
        return 0


def _relay_agent_spans(bench: BenchHost, run_id: str, spans: Spans,
                       cfg: Config, subject: str, name: str) -> None:
    """Ship the bench's self-report drop file (OTLP/HTTP-JSON at
    $WORKSPACE_DIR/gentar-otlp.json, if any) to otelcol. Best-effort,
    like all telemetry: a missing file is normal (most scenarios don't
    self-report); a failed relay warns and moves on."""
    rc, out = bench.exec(
        run_id, "cat \"$WORKSPACE_DIR/gentar-otlp.json\" 2>/dev/null")
    if rc != 0 or not out.strip():
        return
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{cfg.otlp_endpoint}/v1/traces",
            data=out.encode(), method="POST",
            headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        spans.emit(subject, run_id, name, "otlp.relay", "pass",
                   attrs={"endpoint": cfg.otlp_endpoint},
                   detail=f"relayed {len(out)} bytes of agent self-report")
    except Exception as exc:
        print(f"warn: agent self-report relay failed (non-fatal): {exc}")


def run(name: str, cfg: Config | None = None) -> int:
    cfg = cfg or Config()

    # -- quarantine: skip, never fail -----------------------------------
    if name in cfg.quarantine:
        print(f"SKIP [{name}]: quarantined (known flake — not a failure)")
        spans = Spans(cfg)
        skip_id = new_run_id(cfg.name_prefix)
        spans.emit(ARENA_SUBJECT, skip_id, name, "run", "skip",
                   attrs={"quarantined": "true"},
                   detail="quarantined scenario skipped")
        return 0

    try:
        fn, scenario = _resolve(name, cfg)
    except (RunError, ScenarioError) as exc:
        # ScenarioError = malformed/off-schema TOML in a scenarios dir —
        # a usage error (2), same as an unknown name, never a traceback.
        print(f"Error: {exc}")
        return 2

    # -- stub guard: refuse before any bench exists ----------------------
    # A scaffolded scenario (`gentar subject init`) whose verify probes
    # still carry TODO stubs is not a test yet — running it anyway could
    # only fake-green. Refuse with exit 2 (a usage error, never a red
    # bench) exactly like the budget and credential guards.
    if scenario and scenario.stubs:
        msg = (f"stub guard: scenario {name!r} has "
               f"{len(scenario.stubs)} unfilled verify stub(s) "
               f"({', '.join(scenario.stubs)}) — fill the TODO probes "
               f"the scaffold emitted, then run; refusing before any "
               f"bench exists")
        print(f"Error: {msg}")
        spans = Spans(cfg)
        spans.emit(ARENA_SUBJECT, "", name, "stub.refuse", "error",
                   attrs={"stubs": ",".join(scenario.stubs)},
                   detail="run refused: unfilled verify stubs")
        report = RunReport(
            scenario=name,
            run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
            subject=(scenario.subject or ARENA_SUBJECT),
            reproduce=f"docker compose run --rm coordinator run {name}",
            error=msg)
        report.mark("refuse", 2)
        _write_report(report, cfg)
        return 2

    # -- budget guard: refuse before any bench exists ---------------------
    budget_tokens = scenario.budget_tokens if scenario else 0
    if cfg.budget_cap and budget_tokens:
        spans = Spans(cfg)
        already = _spent_so_far(spans)
        if already + budget_tokens > cfg.budget_cap:
            msg = (f"budget guard: run would spend {budget_tokens} units, "
                   f"{already} already burned, cap {cfg.budget_cap}")
            print(f"Error: {msg}")
            spans.emit(ARENA_SUBJECT, "", name, "budget.refuse", "error",
                       attrs={"tokens": str(budget_tokens),
                              "already_burned": str(already),
                              "cap": str(cfg.budget_cap)},
                       detail="run refused by budget guard")
            report = RunReport(
                scenario=name,
                run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
                subject=ARENA_SUBJECT,
                reproduce=f"docker compose run --rm coordinator run {name}",
                error=msg)
            report.mark("refuse", 2)
            _write_report(report, cfg)
            return 2

    # -- credential guard: refuse before any bench exists ----------------
    # Declared credentials (env var names) must be present in the
    # coordinator's environment; a missing one is a usage error (exit 2),
    # not a test failure. Names only in the report — a value must never
    # reach a span, a report, or a log line.
    if scenario and scenario.credentials:
        missing = [c for c in scenario.credentials if not os.environ.get(c)]
        if missing:
            msg = (f"credential guard: scenario {name!r} needs "
                   f"{', '.join(missing)} — not provided (refusing before "
                   f"any bench exists)")
            print(f"Error: {msg}")
            spans = Spans(cfg)
            spans.emit(ARENA_SUBJECT, "", name, "credential.refuse", "error",
                       attrs={"credentials": ",".join(scenario.credentials)},
                       detail="run refused: missing credentials")
            report = RunReport(
                scenario=name,
                run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
                subject=(scenario.subject or ARENA_SUBJECT),
                credentials=scenario.credentials,
                reproduce=f"docker compose run --rm coordinator run {name}",
                error=msg)
            report.mark("refuse", 2)
            _write_report(report, cfg)
            return 2

    subject = (scenario.subject or ARENA_SUBJECT) if scenario else ARENA_SUBJECT
    run_kind = "scripted" if (scenario and scenario.driver_command) else "oracle"
    # Bench tier: the scenario's `bench` key overrides the install default
    # (config bench_kind, "sbx"); builtins always use the default tier.
    bench = make_bench(cfg, kind=(scenario.bench if scenario else ""))
    spans = Spans(cfg)
    run_id = new_run_id(cfg.name_prefix)
    report = RunReport(
        scenario=name, run_id=run_id, subject=subject,
        agent=(scenario.agent if scenario else "shell"),
        template=(scenario.template or "") if scenario else "",
        credentials=(scenario.credentials if scenario else []),
        sandbox=run_id,
        started=time.strftime("%Y-%m-%d %H:%M:%S %z"),
        reproduce=f"docker compose run --rm coordinator run {name}")

    # Provenance is computed once, stamped on both scenario rows. The
    # template digest needs the bench-host; absent template = empty.
    digest = (bench.template_digest(scenario.template)
              if scenario and scenario.template else "")
    attrs = run_attrs(scenario, cfg, name, run_kind,
                      template_digest=digest)
    scen_span = spans.step_start(subject, run_id, name, "scenario",
                                 attrs=attrs)
    t0_ms = int(time.time() * 1000)  # epoch ms — span columns are wall-clock
    spans.emit(subject, run_id, name, "run.start", attrs={"run_id": run_id})

    sandbox = run_id
    verdict = 0
    summary = ""
    try:
        summary = fn(bench, run_id, spans, subject=subject, report=report)
        print(summary)
        # Budget accounting: a passing run burns its declared spend
        # (simulated for no-LLM runs, real token counts later).
        burned = scenario.simulated_spend if scenario else 0
        if burned:
            spans.emit(subject, run_id, name, "budget.spend", "pass",
                       attrs={"tokens": str(burned)},
                       detail="simulated spend recorded")
        spans.emit(subject, run_id, name, "run.end", attrs={"verdict": "pass"})
    except Exception as exc:
        verdict = 1
        report.error = str(exc)
        print(f"FAIL [{name}]: {exc}")
        spans.emit(subject, run_id, name, "run.end", "fail",
                   attrs={"verdict": "fail"}, detail=str(exc)[:2000])
    finally:
        _relay_agent_spans(bench, run_id, spans, cfg, subject, name)
        status = "pass" if verdict == 0 else "fail"
        report.mark(status, verdict)
        report.summary = summary
        spans.step_end(subject, run_id, name, scen_span, "scenario",
                       status, t0_ms, parent="", attrs=attrs,
                       detail=summary if verdict == 0 else "")
        _write_report(report, cfg)
        # The scenario owns a sandbox named run_id; rm is idempotent and
        # warns instead of raising so teardown never masks the verdict.
        # GENTAR_KEEP_BENCH=1 preserves it for post-mortem (debugging).
        if not os.environ.get("GENTAR_KEEP_BENCH"):
            bench.rm(sandbox)

    return verdict
