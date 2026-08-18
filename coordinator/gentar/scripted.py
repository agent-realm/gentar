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


def run_turns(scenario, bench: BenchHost, run_id: str, spans: Spans) -> str:
    driver = PtyDriver(bench, run_id)
    driver.start(scenario.driver_command)
    spans.emit(run_id, "driver.start",
               attrs={"command": scenario.driver_command[:120]})
    try:
        for i, turn in enumerate(scenario.turns):
            kind = turn["type"]
            if kind == "answer":
                prompt = turn["prompt"]
                if not _await(driver, re.compile(prompt, re.IGNORECASE), turn.get("timeout", 60)):
                    raise TurnFailure(f"turn {i}: prompt {prompt!r} never appeared")
                driver.send_line(turn.get("send", ""))
                _ok(spans, run_id, i, f"answer {prompt!r}")
            elif kind == "expect":
                pattern = turn["pattern"]
                if not driver.drive_until(pattern, turn.get("timeout", 90)):
                    raise TurnFailure(f"turn {i}: pattern {pattern!r} never appeared")
                _ok(spans, run_id, i, f"expect {pattern!r}")
            elif kind == "pick":
                if not driver.pick_option(turn["label"], turn.get("tries", 8)):
                    raise TurnFailure(f"turn {i}: picker option /{turn['label']}/ not reachable")
                _ok(spans, run_id, i, f"pick /{turn['label']}/")
            elif kind == "abort":
                try:
                    driver.drive_until("__never_matches__", turn.get("timeout", 30))
                except DriverAbort as abort:
                    _ok(spans, run_id, i, "danger gate fired")
                    spans.emit(run_id, "driver.abort", attrs={"turn": str(i)},
                               body=str(abort))
                    return f"danger gate ok: {abort}"
                raise TurnFailure(f"turn {i}: danger gate did NOT fire")
        driver.wait_idle(60)
        return f"driver ok: {len(scenario.turns)} turns"
    finally:
        spans.emit(run_id, "driver.transcript", body=driver.transcript[-8000:])
        driver.close()


def _await(driver: PtyDriver, pattern: re.Pattern, max_seconds: int) -> bool:
    """Plain wait (no auto-approval) — for prompts the script itself asks."""
    waited = 0.0
    while waited < max_seconds:
        if pattern.search(driver.screen()):
            return True
        time.sleep(0.5); waited += 0.5
    return False


def _ok(spans: Spans, run_id: str, index: int, what: str) -> None:
    spans.emit(run_id, "driver.turn", attrs={"turn": str(index)}, body=what)
