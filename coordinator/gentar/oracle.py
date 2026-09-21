"""Oracle runner — no-LLM execution path. Delivers the subject into the
bench workspace, runs the scenario's reference solution verbatim, then
asserts verdicts from reality. The same assertions are reused unchanged
by the agent driver; only the executor differs."""

import os
import time

from gentar.asserts import AssertResult, check_commands, check_files
from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.report import AssertRecord, RunReport, StepRecord
from gentar.spans import Spans
from gentar.toml_scenario import TomlScenario, satisfied_group


def _step(bench: BenchHost, subject: str, run_id: str, scenario_name: str,
          spans: Spans, index: int, command: str,
          env: dict[str, str] | None = None,
          report: RunReport | None = None) -> None:
    """One oracle step as a two-row span; a nonzero exit fails the run."""
    span = spans.step_start(subject, run_id, scenario_name,
                            f"oracle.step.{index}")
    t0 = int(time.time() * 1000)  # epoch ms — span columns are wall-clock
    rc, out = bench.exec(run_id, command, env=env)
    spans.step_end(subject, run_id, scenario_name, span, f"oracle.step.{index}",
                   "pass" if rc == 0 else "fail", t0,
                   attrs={"exit_code": str(rc)},
                   detail=f"$ {command}\n{out.strip()[:2000]}")
    if report is not None:
        report.steps.append(
            StepRecord(index=index, command=command, exit_code=rc, output=out))
    if rc != 0:
        raise AssertionError(
            f"oracle step {index} failed rc={rc}: {command}\n{out.strip()[:400]}")


def cred_env(scenario: TomlScenario) -> dict[str, str]:
    """The ONE winning alternative group, forwarded whole — the tier-1
    transport (env vars on a throwaway bench).

    Not every declared name that happens to be set: a second, partially
    configured alternative would then ride along and reconfigure the
    winner. Concretely, `ANTHROPIC_API_KEY` satisfies the guard while a
    stray `ANTHROPIC_BASE_URL` (its token absent, so its own group never
    won) redirects that key at another endpoint — the exact mixed
    provider the all-of grouping exists to prevent (PR #26 review round
    3). The guard in coordinator.run refused already when no group was
    complete; if a caller reaches here anyway, forward nothing rather
    than a half provider."""
    group = satisfied_group(scenario.credential_groups(), os.environ.get)
    return {c: os.environ[c] for c in (group or [])}


def run_env(scenario: TomlScenario) -> dict[str, str]:
    """Everything the bench run needs from the coordinator's env:
    guarded credentials plus optional pass_env knobs (non-secret, no
    guard — unset = default behavior, e.g. a cheaper model pin)."""
    env = cred_env(scenario)
    env.update({c: os.environ[c] for c in scenario.pass_env
                if os.environ.get(c)})
    return env


def run_oracle(scenario: TomlScenario, bench: BenchHost, run_id: str,
               spans: Spans, cfg: Config, subject: str = "arena",
               report: RunReport | None = None) -> str:
    workspace = bench.workspace(run_id)
    name = scenario.name

    # 1. Fresh bench + subject delivery, order per tier: sbx wants the
    # workspace populated BEFORE create (a tar touching the bind-mount
    # root after create breaks sbx's mount — exec fails getcwd EPERM,
    # reproduced on VM 142 with both GNU and bsdtar streams); tart has
    # no choice — the workspace lives inside the VM, which must boot
    # first. push_before_create on the host states which world we're in.
    def _create() -> None:
        bench.create(run_id, agent=scenario.agent,
                     template=scenario.template)
        attrs = {"sandbox": run_id, "agent": scenario.agent}
        if scenario.template:
            attrs["template"] = scenario.template
            attrs["template_digest"] = bench.template_digest(
                scenario.template)
        spans.emit(subject, run_id, name, "bench.create", attrs=attrs)

    def _push() -> None:
        if not scenario.subject:
            return
        local_subject = f"{cfg.subjects_root}/{scenario.subject}"
        bench.push_dir(local_subject, workspace)
        spans.emit(subject, run_id, name, "subject.push",
                   attrs={"subject": scenario.subject, "into": workspace})

    if bench.push_before_create:
        _push()
        _create()
    else:
        _create()
        _push()

    # 3. Reference solution, verbatim. Steps run with the run id (and
    # the OTLP endpoint, when configured) in their env, so subject
    # scripts can self-report spans tagged back to this run.
    step_env = {"GENTAR_RUN_ID": run_id}
    if cfg.otlp_endpoint:
        step_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = cfg.otlp_endpoint
    step_env.update(run_env(scenario))
    for i, step_text in enumerate(scenario.steps):
        _step(bench, subject, run_id, name, spans, i, step_text, env=step_env,
              report=report)

    # 3b. Interactive driver turns (scripted today; agents phase 6).
    if scenario.driver_command:
        from gentar.scripted import run_turns
        summary = run_turns(scenario, bench, run_id, spans, subject=subject,
                            env=run_env(scenario), report=report)
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
        if report is not None:
            report.asserts.append(
                AssertRecord(check=r.name, ok=r.ok, detail=r.detail))
        spans.emit(subject, run_id, name, "assert",
                   "pass" if r.ok else "fail",
                   attrs={"check": r.name}, detail=r.detail)
    if failed:
        raise AssertionError(
            f"{failed}/{len(results)} assertions failed — "
            + "; ".join(f"{r.name}: {r.detail}" for r in results if not r.ok))

    ok = sum(1 for r in results)
    return f"oracle ok: {ok}/{len(results)} assertions passed"
