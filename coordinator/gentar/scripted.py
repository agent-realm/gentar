"""Scripted driver turns — applies a scenario's [driver] block to the
pty: answer prompts, expect patterns, navigate pickers, and prove the
danger gate fires. The same PtyDriver serves the agent adapters; only
the turn source differs (scripted TOML vs a live agent's choices).
"""

import re
import time

from gentar.benchhost import BenchHost
from gentar.pty_driver import DriverAbort, PtyDriver
from gentar.spans import Spans


class TurnFailure(AssertionError):
    pass


def run_turns(scenario, bench: BenchHost, run_id: str, spans: Spans,
              subject: str = "arena",
              env: dict[str, str] | None = None,
              report=None) -> str:
    name = scenario.name
    driver = PtyDriver(bench, run_id)
    driver.start(scenario.driver_command, env=env)
    spans.emit(subject, run_id, name, "driver.start",
               attrs={"command": scenario.driver_command[:120]})
    try:
        for i, turn in enumerate(scenario.turns):
            kind = turn["type"]
            if kind == "answer":
                prompt = turn["prompt"]
                if not _await(driver, re.compile(prompt, re.IGNORECASE), turn.get("timeout", 60)):
                    raise TurnFailure(f"turn {i}: prompt {prompt!r} never appeared")
                driver.send_line(turn.get("send", ""))
                _ok(spans, subject, run_id, name, i, f"answer {prompt!r}")
            elif kind == "expect":
                pattern = turn["pattern"]
                if not driver.drive_until(pattern, turn.get("timeout", 90)):
                    raise TurnFailure(f"turn {i}: pattern {pattern!r} never appeared")
                _ok(spans, subject, run_id, name, i, f"expect {pattern!r}")
            elif kind == "pick":
                if not driver.pick_option(turn["label"], turn.get("tries", 8)):
                    raise TurnFailure(f"turn {i}: picker option /{turn['label']}/ not reachable")
                _ok(spans, subject, run_id, name, i, f"pick /{turn['label']}/")
            elif kind == "abort":
                try:
                    driver.drive_until("__never_matches__", turn.get("timeout", 30))
                except DriverAbort as abort:
                    _ok(spans, subject, run_id, name, i, "danger gate fired")
                    spans.emit(subject, run_id, name, "driver.abort",
                               attrs={"turn": str(i)}, detail=str(abort))
                    return f"danger gate ok: {abort}"
                raise TurnFailure(f"turn {i}: danger gate did NOT fire")
        # Wait for the command itself to finish (EOF), not for a quiet
        # screen — headless agents are silent mid-run. Headless
        # scenarios bound themselves (`timeout` in the command); 300s
        # covers the tail of a scripted one.
        driver.wait_done(300)
        return f"driver ok: {len(scenario.turns)} turns"
    finally:
        spans.emit(subject, run_id, name, "driver.transcript",
                   detail=driver.transcript[-8000:])
        if report is not None:
            report.transcript = driver.transcript
        driver.close()


def _await(driver: PtyDriver, pattern: re.Pattern, max_seconds: int) -> bool:
    """Plain wait (no auto-approval) — for prompts the script itself asks."""
    waited = 0.0
    while waited < max_seconds:
        if pattern.search(driver.screen()):
            return True
        time.sleep(0.5); waited += 0.5
    return False


def _ok(spans: Spans, subject: str, run_id: str, name: str,
        index: int, what: str) -> None:
    spans.emit(subject, run_id, name, "driver.turn",
               attrs={"turn": str(index)}, detail=what)
