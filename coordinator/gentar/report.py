"""Run report v1 — the artifact that closes the loop: run a scenario,
get a markdown report stating exactly what happened, feed it to an
agent (or a human) to fix. Written on EVERY terminal outcome of a run
(pass, fail, refuse); the filename carries the run id.

The report states facts the way an agent needs them: what ran, in what
order, with what output, which assertions failed and what they saw."""

import time
from dataclasses import dataclass, field
from pathlib import Path

# Output tails: enough to act on, not enough to drown a context window.
_STEP_TAIL = 1200
_DETAIL_TAIL = 600


def _tail(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


@dataclass
class StepRecord:
    index: int
    command: str
    exit_code: int
    output: str = ""


@dataclass
class AssertRecord:
    check: str
    ok: bool
    detail: str = ""


@dataclass
class RunReport:
    scenario: str
    run_id: str
    subject: str = "arena"
    agent: str = "shell"
    template: str = ""
    # Env var NAMES a run required — names only; a value must never
    # reach a report.
    credentials: list[str] = field(default_factory=list)
    sandbox: str = ""
    started: str = ""
    reproduce: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    asserts: list[AssertRecord] = field(default_factory=list)
    # Raw pty transcript when a driver ran — the evidence behind an
    # agent-in-the-loop verdict. Tail-rendered; values of declared
    # credentials never appear (they are env, not output).
    transcript: str = ""
    verdict: str = "pass"          # pass | fail | refuse
    exit_code: int = 0
    error: str = ""
    # Things that did not change the verdict but could explain it — e.g. a
    # declared credential that was set and still not forwarded.
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    # Numbers derived from the agent's session transcript(s), if any ran
    # (gentar.agentstats) — counts only, never transcript text.
    agent_stats: dict = field(default_factory=dict)
    # Soft [[verify.judge]] results — reported, never the verdict.
    soft: list = field(default_factory=list)
    # When a driver turn failed: the last screen, the raw byte tail, the
    # bench's process tree, [on_failure] output (scripted.failure_snapshot).
    failure: dict = field(default_factory=dict)

    def mark(self, verdict: str, exit_code: int) -> None:
        self.verdict = verdict
        self.exit_code = exit_code

    def write(self, directory: str | Path) -> Path:
        path = Path(directory) / f"report-{self.run_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.markdown())
        # The report dir is a host bind; the coordinator runs as root in
        # the container, so root would own the artifacts and the host
        # user could not clean them (CI workspaces died on EACCES).
        # World-writable test artifacts are fine — they carry no secrets.
        import os
        os.chmod(path, 0o666)
        try:
            os.chmod(path.parent, 0o777)
        except OSError:
            pass
        return path

    def markdown(self) -> str:
        finished = time.strftime("%Y-%m-%d %H:%M:%S %z")
        lines: list[str] = []
        lines.append(f"# gentar report — {self.scenario}: {self.verdict.upper()}")
        lines.append("")
        lines.append("| field | value |")
        lines.append("|---|---|")
        for key, value in [
            ("run_id", self.run_id),
            ("verdict", f"{self.verdict} (exit {self.exit_code})"),
            ("subject", self.subject),
            ("bench agent", self.agent + (f" (template {self.template})" if self.template else "")),
            ("credentials", ", ".join(self.credentials) or "-"),
            ("sandbox", self.sandbox or "-"),
            ("started", self.started or "-"),
            ("written", finished),
        ]:
            lines.append(f"| {key} | `{value}` |")
        lines.append("")
        lines.append(f"Reproduce: `{self.reproduce}`")
        lines.append("")

        if self.warnings:
            lines.append("## Warnings")
            lines.append("")
            for w in self.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if self.error:
            lines.append("## Failure")
            lines.append("")
            lines.append("```")
            lines.append(_tail(self.error, 2000))
            lines.append("```")
            lines.append("")

        if self.steps:
            lines.append("## Steps")
            lines.append("")
            for s in self.steps:
                mark = "pass" if s.exit_code == 0 else f"FAIL (exit {s.exit_code})"
                lines.append(f"### {s.index}. {mark}")
                lines.append("")
                lines.append("```sh")
                lines.append(_tail(s.command, 400))
                lines.append("```")
                if s.output:
                    lines.append("")
                    lines.append("```")
                    lines.append(_tail(s.output, _STEP_TAIL))
                    lines.append("```")
                lines.append("")

        if self.failure:
            f = self.failure
            lines.append("## Failure snapshot (the pilot's session when the turn failed)")
            lines.append("")
            for title, key in (("Last screen", "screen"), ("Raw tail of the pty stream "
                               "(escapes shown as \\xNN)", "raw_tail"),
                               ("Processes in the bench", "processes")):
                lines += [f"### {title}", "", "```", (f.get(key) or "(empty)").rstrip(), "```", ""]
            for h in f.get("on_failure") or []:
                lines += [f"### on_failure: `{h['command']}`", "", "```",
                          (h.get("output") or "").rstrip(), "```", ""]

        if self.soft:
            lines.append("## Soft judgments (reported only — not the verdict)")
            lines.append("")
            lines.append("| question | result | detail |")
            lines.append("|---|---|---|")
            for s in self.soft:
                lines.append(f"| {_tail(s['question'], 160)} | {s['status']} | {_tail(s['detail'], 120)} |")
            lines.append("")

        if self.asserts:
            failed = sum(1 for a in self.asserts if not a.ok)
            lines.append(f"## Assertions ({len(self.asserts) - failed}/{len(self.asserts)} passed)")
            lines.append("")
            lines.append("| check | result | detail |")
            lines.append("|---|---|---|")
            for a in self.asserts:
                detail = _tail(a.detail, _DETAIL_TAIL).replace("|", "\\|").replace("\n", " ")
                lines.append(f"| `{a.check}` | {'✅ pass' if a.ok else '❌ FAIL'} | {detail} |")
            lines.append("")

        if self.transcript:
            lines.append("## Driver transcript")
            lines.append("")
            lines.append("```")
            lines.append(_tail(self.transcript, 4000))
            lines.append("```")
            lines.append("")

        if self.agent_stats.get("turns"):
            a = self.agent_stats
            lines.append("## Agent (from its session transcript — numbers only)")
            lines.append("")
            lines.append("| sessions | turns | input tokens | output tokens | cache read | cache write | tool calls | tool errors |")
            lines.append("|---|---|---|---|---|---|---|---|")
            lines.append(f"| {a['sessions']} | {a['turns']} | {a['input_tokens']} | "
                         f"{a['output_tokens']} | {a['cache_read_tokens']} | "
                         f"{a['cache_creation_tokens']} | {a['tool_calls']} | {a['tool_errors']} |")
            lines.append("")

        if self.summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(self.summary)
            lines.append("")
        return "\n".join(lines)
