"""Oracle runner — phase 2's no-LLM execution path. Delivers the subject
into the bench workspace, runs the scenario's reference solution
verbatim, then asserts verdicts from reality. The same assertions are
reused unchanged by the phase-3 agent driver; only the executor differs.
"""

from gentar.asserts import AssertResult, check_commands, check_files
from gentar.benchhost import BenchHost
from gentar.config import Config
from gentar.spans import Spans
from gentar.toml_scenario import TomlScenario


def run_oracle(scenario: TomlScenario, bench: BenchHost, run_id: str,
               spans: Spans, cfg: Config) -> str:
    sandbox = run_id
    workspace = bench.workspace(sandbox)

    # 1. Deliver the subject into the workspace (mounted, never baked).
    if scenario.subject:
        local_subject = f"{cfg.subjects_root}/{scenario.subject}"
        bench.push_dir(local_subject, workspace)
        spans.emit(run_id, "subject.push",
                   attrs={"subject": scenario.subject, "into": workspace})

    # 2. Fresh bench with the workspace bind-mounted.
    bench.create(sandbox, agent=scenario.agent)
    spans.emit(run_id, "bench.create",
               attrs={"sandbox": sandbox, "agent": scenario.agent})

    # 3. Reference solution, verbatim. A failing step fails the run.
    for i, step in enumerate(scenario.steps):
        rc, out = bench.exec(sandbox, step)
        spans.emit(run_id, "oracle.step",
                   attrs={"index": str(i), "exit_code": str(rc)},
                   body=f"$ {step}\n{out.strip()[:2000]}")
        if rc != 0:
            raise AssertionError(
                f"oracle step {i} failed rc={rc}: {step}\n{out.strip()[:400]}")

    # 4. Verdicts from reality.
    rc, home = bench.exec(sandbox, "echo $HOME")
    home = home.strip()
    results: list[AssertResult] = (
        check_files(bench, sandbox, home, scenario.files)
        + check_commands(bench, sandbox, scenario.commands)
    )
    failed = 0
    for r in results:
        if not r.ok:
            failed += 1
        spans.emit(run_id, "assert", "ok" if r.ok else "fail",
                   attrs={"check": r.name}, body=r.detail)
    if failed:
        raise AssertionError(
            f"{failed}/{len(results)} assertions failed — see assert spans")

    ok = sum(1 for r in results)
    return f"oracle ok: {ok}/{len(results)} assertions passed"
