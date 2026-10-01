"""Run loop: one scenario, one sandbox lifetime, verdict from reality.

The run itself is a TWO-ROW scenario span (gauntlet policy, ported):
a `running` row opens it, the terminal row carries status/duration and
the full provenance attrs — stamped on BOTH rows, because the terminal
row is the one a duration-comparison query selects. Exit code is the
verdict: 0 pass · 1 fail · 2 usage/config refusal. Dispatches Python
builtins (smoke) and TOML scenarios (oracle runner)."""

import os
import shlex
import time

from gentar.benchhost import BenchHost, make_bench
from gentar.config import Config
from gentar.oracle import run_oracle
from gentar.provenance import run_attrs
from gentar.report import RunReport
from gentar.scenarios import REGISTRY, known_names
from gentar.spans import Spans, agent_rows, exporting, new_run_id
from gentar.toml_scenario import (TomlScenario, credentials_satisfied,
                                  dropped_credentials, satisfied_group,
                                  load_dir)

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


# Where Claude Code keeps session transcripts: <config dir>/projects/<cwd>/
# <session>.jsonl, the config dir being ~/.claude or a playbook's own.
_TRANSCRIPTS = ("find \"$HOME\" -maxdepth 7 -path '*/projects/*' -name '*.jsonl' "
                "-size -20M 2>/dev/null | head -20")


def _collect_agent_stats(bench: BenchHost, run_id: str, spans: Spans,
                         subject: str, name: str, report) -> None:
    """Numbers from the agent's session transcript(s), if an agent ran:
    tokens, turns, tool calls — into the arena, the export and the report.
    The transcript text is read into memory here and dropped; agentstats
    returns numbers and labels only. Best-effort, never the verdict."""
    try:
        rc, listing = bench.exec(run_id, _TRANSCRIPTS, timeout=60)
        paths = [p for p in listing.splitlines() if p.strip()] if rc == 0 else []
        if not paths:
            return
        texts = []
        for p in paths:
            rc, text = bench.exec(run_id, f"cat {shlex.quote(p)}", timeout=120)
            if rc == 0:
                texts.append(text)
        from gentar.agentstats import extract
        turns, tools, totals = extract(texts)
        del texts
        if not turns:
            return
        agent_rows(spans, subject, run_id, name, turns, tools)
        report.agent_stats = totals
        spans.emit(subject, run_id, name, "agent.stats", "pass",
                   attrs={k: str(v) for k, v in totals.items()},
                   detail=f"{totals['turns']} turns, {totals['tool_calls']} tool calls, "
                          f"{totals['input_tokens'] + totals['output_tokens']} tokens")
    except Exception as exc:
        print(f"warn: agent stats not collected (non-fatal): {type(exc).__name__}")


def _relay_agent_spans(bench: BenchHost, run_id: str, spans: Spans,
                       cfg: Config, subject: str, name: str) -> None:
    """Ship the bench's self-report drop file (OTLP/HTTP-JSON at
    $WORKSPACE_DIR/gentar-otlp.json, if any) to otelcol. Best-effort,
    like all telemetry: a missing file is normal (most scenarios don't
    self-report); a failed relay warns and moves on. It runs in the run's
    `finally`, so NOTHING here may raise: a bench that hangs (the read times
    out) once escaped and skipped the scenario's end, report and teardown."""
    try:
        rc, out = bench.exec(
            run_id, "cat \"$WORKSPACE_DIR/gentar-otlp.json\" 2>/dev/null")
    except Exception as exc:
        print(f"warn: agent self-report not read (non-fatal): {type(exc).__name__}")
        return
    if rc != 0 or not out.strip():
        return
    # The copy that may leave the arena goes scrubbed, through its own door;
    # the raw file below reaches the local ClickHouse only.
    spans.otlp.relay(subject, run_id, out)
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
    """Run one scenario; every terminal path — pass, fail, refusal,
    quarantine — then flushes its trace (best-effort, never the verdict)."""
    cfg = cfg or Config()
    runs, rate_min = _rate_plan(name, cfg)
    if runs <= 1:
        with exporting():
            return _run(name, cfg)
    return _run_rate(name, cfg, runs, rate_min)


def _rate_plan(name: str, cfg: Config) -> tuple:
    """(runs, pass_rate_min) from the scenario's [semantic] table; (1, 1.0)
    for a builtin, an unknown name (let _run refuse it) or no table."""
    try:
        _, scenario = _resolve(name, cfg)
    except RunError:
        return 1, 1.0
    if scenario is None or name in cfg.quarantine:
        return 1, 1.0                   # quarantine skips once, it does not "pass" N times
    return int(getattr(scenario, "semantic_runs", 1)), float(getattr(scenario, "pass_rate_min", 1.0))


def _rate_budget_refusal(name: str, cfg: Config, runs: int) -> str:
    """The WHOLE rate's spend, checked before the first bench (Codex): one
    repetition within the cap and the next refused would be an exit 2 after
    a bench already existed."""
    try:
        _, scenario = _resolve(name, cfg)
    except RunError:
        return ""
    each = scenario.budget_tokens if scenario else 0
    if not (cfg.budget_cap and each):
        return ""
    with exporting():
        already = _spent_so_far(Spans(cfg))
    if already + each * runs > cfg.budget_cap:
        return (f"budget guard: {runs} runs x {each} units would spend {each * runs}, "
                f"{already} already burned, cap {cfg.budget_cap} (refusing before any bench exists)")
    return ""


def _run_rate(name: str, cfg: Config, runs: int, rate_min: float) -> int:
    """A judged suite's verdict over N runs, each on a fresh bench: exit 0
    iff passes/N >= pass_rate_min. A refusal (exit 2) ends it at once — it
    would refuse every time. Stops early once the minimum is out of reach
    (every further run is judge calls spent on a known verdict)."""
    import math
    refusal = _rate_budget_refusal(name, cfg, runs)
    if refusal:
        print(f"Error: {refusal}")
        return 2
    need = math.ceil(rate_min * runs - 1e-9)
    passes = done = 0
    for i in range(runs):
        print(f"semantic run {i + 1}/{runs} of {name}")
        with exporting():
            rc = _run(name, cfg)
        if rc == 2:
            return 2
        done += 1
        passes += rc == 0
        if passes + (runs - done) < need:
            print(f"semantic rate: {passes}/{done} so far — {need}/{runs} is out of reach, stopping")
            break
    rate = passes / runs
    ok = passes >= need
    print(f"semantic rate of {name}: {passes}/{runs} passed ({rate:.2f}; needs {rate_min:.2f}) "
          f"— {'PASS' if ok else 'FAIL'}")
    with exporting():
        Spans(cfg).emit(ARENA_SUBJECT, new_run_id(cfg.name_prefix), name, "semantic.rate",
                        "pass" if ok else "fail",
                        attrs={"runs": str(runs), "run": str(done), "passes": str(passes),
                               "pass_rate_min": str(rate_min)},
                        detail=f"{passes}/{runs} passed")
    return 0 if ok else 1


def _run(name: str, cfg: Config | None = None) -> int:
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
    except RunError as exc:
        print(f"Error: {exc}")
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
    # Declared credentials (env var names) name the env vars a bench may
    # need. Entries are ALTERNATIVE providers, not conjunctions: a
    # scenario can declare ANTHROPIC_API_KEY (first-party) alongside
    # ANTHROPIC_AUTH_TOKEN+ANTHROPIC_BASE_URL (any Anthropic-compatible
    # endpoint — GLM coding plan, routers, proxies) and each runner sets
    # the one it has — but a provider that IS a pair travels as a group
    # entry (all-or-nothing): a token without its endpoint is half a
    # provider and must refuse, not start a misconfigured bench (PR #26
    # review). The guard refuses (exit 2) when NO group is fully present
    # — no auth at all is a usage error, not a test failure; a
    # present-but-invalid value fails auth INSIDE the bench, honestly,
    # with the transcript as evidence. Names only in the report — a
    # value must never reach a span, a report, or a log line.
    if scenario and scenario.credentials:
        groups = scenario.credential_groups()
        if not credentials_satisfied(groups, os.environ.get):
            shapes = ", ".join("+".join(g) if len(g) > 1 else g[0]
                               for g in groups)
            msg = (f"credential guard: scenario {name!r} needs at least "
                   f"one of {shapes} — no group fully provided (refusing "
                   f"before any bench exists)")
            print(f"Error: {msg}")
            spans = Spans(cfg)
            spans.emit(ARENA_SUBJECT, "", name, "credential.refuse", "error",
                       attrs={"credentials": ",".join(scenario.credential_names())},
                       detail="run refused: missing credentials")
            report = RunReport(
                scenario=name,
                run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
                subject=(scenario.subject or ARENA_SUBJECT),
                credentials=scenario.credential_names(),
                reproduce=f"docker compose run --rm coordinator run {name}",
                error=msg)
            report.mark("refuse", 2)
            _write_report(report, cfg)
            return 2

    # -- judge guard: refuse before any bench exists ---------------------
    # A semantic turn sends the current screen to a judge (TypeSafe). That
    # is allowed only for a scenario that declares its data synthetic
    # (pilot, 2026-09-26) — refusing here, not mid-run, means no bench and
    # no screen ever exists for a scenario that may not use one. A missing
    # key is refused the same way: a semantic suite without its judge is
    # a usage error, never a pass. Names only; the key never reaches a log.
    if scenario and getattr(scenario, "uses_judge", False):
        from gentar.judge import KEY_NAME, TypeSafeBackend, egress_allowed
        problem = ""
        if not egress_allowed(scenario, TypeSafeBackend):
            problem = (f"judge guard: scenario {name!r} uses a judged turn but does "
                       f"not declare [scenario] data = \"synthetic\" — no screen may "
                       f"leave the arena (refusing before any bench exists)")
        elif not os.environ.get(KEY_NAME):
            problem = (f"judge guard: scenario {name!r} uses a judged turn and "
                       f"{KEY_NAME} is not set (refusing before any bench exists)")
        if problem:
            print(f"Error: {problem}")
            spans = Spans(cfg)
            spans.emit(ARENA_SUBJECT, "", name, "judge.refuse", "error",
                       attrs={"data": scenario.data or "(undeclared)"},
                       detail="run refused: judge guard")
            report = RunReport(
                scenario=name,
                run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
                subject=(scenario.subject or ARENA_SUBJECT),
                reproduce=f"docker compose run --rm coordinator run {name}",
                error=problem)
            report.mark("refuse", 2)
            _write_report(report, cfg)
            return 2

    # A declared credential that is SET but sits outside the winning group
    # is dropped — correctly — but never silently: see dropped_credentials.
    # Names only; a value never reaches a log line.
    cred_warnings: list[str] = list(getattr(scenario, "warnings", []) or [])
    for w in cred_warnings:
        print(f"warning: {w}")
    if scenario and scenario.credentials:
        dropped = dropped_credentials(scenario.credential_groups(), os.environ.get)
        if dropped:
            won = satisfied_group(scenario.credential_groups(),
                                  os.environ.get) or []
            pair = ", ".join('"%s"' % n for n in won + dropped[:1])
            cred_warnings.append(
                "credential(s) %s are set but NOT forwarded to the bench: %s "
                "won as its own alternative. If they belong together, declare "
                "them as one group — credentials = [[%s]] — a flat list means "
                "any ONE of, not ALL of."
                % (", ".join(dropped), "+".join(won), pair))
            print(f"warning: {cred_warnings[-1]}")

    # -- bench-config guard: refuse before any bench exists --------------
    # The bench tier this run will actually use — the scenario's `bench`
    # key, else the install default. Install-identity vars (which host,
    # which account) have no defaults in config.py: unset means this
    # install was never configured, which is a usage error (exit 2), not
    # a test failure. Refusing here rather than at Config load keeps an
    # unused tier's absence harmless — an sbx-only install never has to
    # configure tart. Names only; a value must never reach a log line.
    bench_kind = (scenario.bench if scenario and scenario.bench
                  else cfg.bench_kind)
    missing = cfg.missing_bench_env(bench_kind)
    if missing:
        # Two shapes: an unknown tier names what it needs in prose, a
        # known-but-unconfigured one names env vars that are unset.
        if len(missing) == 1 and missing[0].startswith("a "):
            msg = (f"bench config: {missing[0]} — refusing before any "
                   f"bench exists.")
        else:
            msg = (f"bench config: {bench_kind} benches need "
                   f"{' and '.join(missing)} — unset (refusing before any "
                   f"bench exists). Copy .env.example to .env and set it.")
        print(f"Error: {msg}")
        spans = Spans(cfg)
        spans.emit(ARENA_SUBJECT, "", name, "bench.config.refuse", "error",
                   attrs={"bench_kind": bench_kind,
                          "missing": ",".join(missing)},
                   detail="run refused: bench tier not configured")
        report = RunReport(
            scenario=name,
            run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
            subject=(scenario.subject if scenario and scenario.subject
                     else ARENA_SUBJECT),
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
    # -- host guard: refuse before any bench exists ----------------------
    # What the config cannot know: the state of the bench-host itself
    # (for sbx, stored secrets its credential proxy would hand to every
    # sandbox). Same refusal contract as above: exit 2, no bench.
    problems = bench.preflight()
    if problems:
        msg = ("bench-host: " + "; ".join(problems)
               + " — refusing before any bench exists.")
        print(f"Error: {msg}")
        Spans(cfg).emit(ARENA_SUBJECT, "", name, "bench.preflight.refuse",
                        "error", attrs={"bench_kind": bench_kind},
                        detail="run refused: bench-host preflight")
        report = RunReport(
            scenario=name,
            run_id=f"refused-{name}-{time.strftime('%Y%m%d-%H%M%S')}",
            subject=subject, reproduce=f"docker compose run --rm coordinator run {name}",
            error=msg)
        report.mark("refuse", 2)
        _write_report(report, cfg)
        return 2
    spans = Spans(cfg)
    # Scrub the values of what this run declared from everything it exports.
    if scenario:
        spans.redactor.redact_values(
            [(n, os.environ.get(n, "")) for n in scenario.credential_names()])
    run_id = new_run_id(cfg.name_prefix)
    report = RunReport(
        scenario=name, run_id=run_id, subject=subject,
        agent=(scenario.agent if scenario else "shell"),
        template=(scenario.template or "") if scenario else "",
        credentials=(scenario.credential_names() if scenario else []),
        sandbox=run_id,
        started=time.strftime("%Y-%m-%d %H:%M:%S %z"),
        reproduce=f"docker compose run --rm coordinator run {name}",
        warnings=list(cred_warnings))

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
        _collect_agent_stats(bench, run_id, spans, subject, name, report)
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
