"""One driller session on a fresh bench, and N of them for a verdict.

run_oracle() calls session() after the scenario's install steps, when the
scenario has a [driller] table. The order is the boundary's:

  1. the sandbox's own rules: an allow a kit added that the brief did not
     name refuses the session before the driller types anything;
  2. the brief's hosts, as one per-sandbox allow rule (none by default);
  3. a snapshot of the host (sandboxes, templates) and the brief (README,
     each `help` command's --help), both read before the driller acts;
  4. the session loop (drill.py);
  5. the sandbox's policy log and a second snapshot: an allowed connection
     off the list, or a change outside the bench, FAILS the session;
  6. notes -> typed findings (BAML) -> kept only with evidence on screen.

A session's exit is the boundary's alone: findings never fail it.
SINK collects every session's findings so the N-run wrapper can rank them.
"""

from __future__ import annotations

import os
import shlex

from gentar import driller as d
from gentar.drill import DrillBudget, drill

# (scenario name, session record) for every session this process ran.
SINK: list[tuple[str, dict]] = []


class BoundaryBreach(AssertionError):
    """The containment did not hold: the session fails, and it is a bug in
    gentar's boundary, not in the subject."""


def _brief(bench, run_id: str, dr: dict, workspace: str, scrub) -> str:
    persona = d.PERSONAS[dr["hat"]]
    # README: relative to the workspace, or absolute, or under ~ (a suite
    # that installs inline writes its own).
    r = dr["readme"]
    path = (f'"$HOME"/{shlex.quote(r[2:])}' if r.startswith("~/")
            else shlex.quote(r if r.startswith("/") else f"{workspace}/{r}"))
    _, readme = bench.exec(run_id, f"cat {path} 2>/dev/null | head -c 20000")
    helps = {}
    for cmd in dr["help"]:
        _, out = bench.exec(run_id, f"{cmd} --help 2>&1 | head -c 8000")
        helps[cmd] = out
    _, installed = bench.exec(run_id, "ls -1 ~/.local/bin /usr/local/bin 2>/dev/null | head -200")
    return scrub(d.brief(persona, readme, helps, [l for l in installed.splitlines() if l.strip()]))


def session(scenario, bench, run_id: str, spans, subject: str, report=None,
            driver_factory=None, model_factory=None, env=None) -> str:
    env = os.environ if env is None else env
    dr = scenario.driller
    name = scenario.name
    scrub = spans.redactor.scrub
    persona = d.PERSONAS[dr["hat"]]

    # 1. rules on THIS sandbox that nobody asked for (sbx kits add their own)
    rules, _ = bench.policy_state(())
    extra = d.sandbox_problems(rules, run_id, dr["allow"])
    if extra:
        raise BoundaryBreach("driller refused before its first keystroke: " + "; ".join(extra))
    # 2. the brief's hosts, or no network at all
    argv = d.policy_argv(run_id, dr["allow"])
    if argv:
        bench.allow_for(run_id, argv)
    # 3. before: the host, the brief
    before = bench.snapshot()
    brief = _brief(bench, run_id, dr, bench.workspace(run_id), scrub)

    # 4. the session
    if driver_factory is None:
        from gentar.pty_driver import PtyDriver
        driver_factory = lambda: PtyDriver(bench, run_id)          # noqa: E731
    if model_factory is None:
        from gentar.drill import BamlModel
        model_factory = lambda: BamlModel(d.model_env(env, dr["model"]))  # noqa: E731
    driver = driver_factory()
    # The brief's credentials only: the scenario's own, as for any suite
    # (the parser already refused every arena-owned name).
    from gentar.oracle import run_env
    driver.start(dr["command"], env=run_env(scenario))
    spans.emit(subject, run_id, name, "driller.start",
               attrs={"hat": dr["hat"],
                      "model": d.model_env(env, dr["model"])["GENTAR_DRILLER_MODEL"]})
    model = model_factory()
    try:
        result = drill(driver, model, persona.charter, brief, scrub,
                       DrillBudget(seconds=dr["seconds"], steps=dr["max_steps"],
                                   calls=dr["max_calls"], input_tokens=dr["max_input_tokens"],
                                   every=dr["every"]),
                       emit=lambda n, a: spans.emit(subject, run_id, name, n, attrs=a))
    finally:
        transcript = getattr(driver, "transcript", "")
        driver.close()

    # 5. after: what got through, what changed
    audit = d.audit(bench.policy_log(run_id), run_id, dr["allow"])
    outside = d.outside_changes(before, bench.snapshot(), {run_id})
    code, reasons = d.verdict(audit, outside, scrub=scrub)

    # 6. notes -> findings, evidence or nothing
    findings, dropped = [], []
    if result.notes:
        try:
            raw = d.extract(persona.hat, result.notes, scrub(transcript[-60000:]),
                            env={**d.model_env(env, dr["model"]),
                                 **{k: env[k] for k in d.FORBIDDEN_ENV if k in env}})
            findings, dropped = d.supported(raw, scrub(transcript))
        except Exception as exc:                        # noqa: BLE001 — reported, not fatal
            reasons_note = f"findings extraction failed: {type(exc).__name__}"
            result.boundary.append(reasons_note)
    record = {"ended": result.ended, "steps": result.steps, "boundary": list(result.boundary),
              "findings": findings, "dropped": len(dropped), "audit": audit,
              "breaches": reasons, "notes": result.notes}
    SINK.append((name, record))
    if report is not None:
        report.transcript = scrub(transcript)
        report.driller = record
    spans.emit(subject, run_id, name, "driller.end", "fail" if code else "pass",
               attrs={"ended": result.ended[:80], "steps": str(result.steps),
                      "findings": str(len(findings)), "blocked": str(len(audit.denied)),
                      "breaches": str(len(reasons))})
    if code:
        raise BoundaryBreach("; ".join(reasons))
    return (f"driller {dr['hat']}: {result.ended} after {result.steps} step(s); "
            f"{len(findings)} supported finding(s), {len(dropped)} dropped; "
            f"{len(audit.denied)} blocked attempt(s)")
