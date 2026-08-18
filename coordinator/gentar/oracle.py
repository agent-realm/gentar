"""Oracle runner — no-LLM execution path. Delivers the subject into the
bench workspace, runs the scenario's reference solution verbatim, then
asserts verdicts from reality. The same assertions are reused unchanged
by the agent driver; only the executor differs."""

import time

from gentar.asserts import AssertResult, check_commands, check_files
from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.spans import Spans
from gentar.toml_scenario import TomlScenario


def _step(bench: BenchHost, subject: str, run_id: str, scenario_name: str,
          spans: Spans, index: int, command: str,
          env: dict[str, str] | None = None) -> None:
    """One oracle step as a two-row span; a nonzero exit fails the run."""
    span = spans.step_start(subject, run_id, scenario_name,
                            f"oracle.step.{index}")
    t0 = int(time.time() * 1000)  # epoch ms — span columns are wall-clock
    rc, out = bench.exec(run_id, command, env=env)
    spans.step_end(subject, run_id, scenario_name, span, f"oracle.step.{index}",
                   "pass" if rc == 0 else "fail", t0,
                   attrs={"exit_code": str(rc)},
                   detail=f"$ {command}\n{out.strip()[:2000]}")
    if rc != 0:
        raise AssertionError(
            f"oracle step {index} failed rc={rc}: {command}\n{out.strip()[:400]}")


def run_oracle(scenario: TomlScenario, bench: BenchHost, run_id: str,
               spans: Spans, cfg: Config, subject: str = "arena") -> str:
    workspace = bench.workspace(run_id)
    name = scenario.name

    # 1. Deliver the subject into the workspace (mounted, never baked).
    if scenario.subject:
        local_subject = f"{cfg.subjects_root}/{scenario.subject}"
        bench.push_dir(local_subject, workspace)
        spans.emit(subject, run_id, name, "subject.push",
                   attrs={"subject": scenario.subject, "into": workspace})

    # 2. Fresh bench with the workspace bind-mounted. A scenario with a
    # template creates from it (agent CLIs pre-installed); template tag +
    # image digest land in the span for provenance.
    bench.create(run_id, agent=scenario.agent, template=scenario.template)
    attrs = {"sandbox": run_id, "agent": scenario.agent}
    if scenario.template:
        attrs["template"] = scenario.template
        attrs["template_digest"] = bench.template_digest(scenario.template)
    spans.emit(subject, run_id, name, "bench.create", attrs=attrs)

    # 3. Reference solution, verbatim. Steps run with the run id (and
    # the OTLP endpoint, when configured) in their env, so subject
    # scripts can self-report spans tagged back to this run.
    step_env = {"GENTAR_RUN_ID": run_id}
    if cfg.otlp_endpoint:
        step_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = cfg.otlp_endpoint
    for i, step_text in enumerate(scenario.steps):
        _step(bench, subject, run_id, name, spans, i, step_text, env=step_env)

    # 3b. Interactive driver turns (scripted today; agents phase 6).
    if scenario.driver_command:
        from gentar.scripted import run_turns
        summary = run_turns(scenario, bench, run_id, spans, subject=subject)
        if not scenario.files and not scenario.commands:
            return summary

    # 4. Verdicts from reality.
    rc, home = bench.exec(run_id, "echo $HOME")
    home = home.strip()
    results: list[AssertResult] = (
        check_files(bench, run_id, home, scenario.files)
        + check_commands(bench, run_id, scenario.commands)
    )
    failed = 0
    for r in results:
        if not r.ok:
            failed += 1
        spans.emit(subject, run_id, name, "assert",
                   "pass" if r.ok else "fail",
                   attrs={"check": r.name}, detail=r.detail)
    if failed:
        raise AssertionError(
            f"{failed}/{len(results)} assertions failed — see assert spans")

    ok = sum(1 for r in results)
    return f"oracle ok: {ok}/{len(results)} assertions passed"
