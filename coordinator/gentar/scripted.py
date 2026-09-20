"""Scripted driver turns — applies a scenario's [driver] block to the
pty: answer prompts, expect patterns, navigate pickers, and prove the
danger gate fires. The same PtyDriver serves the agent adapters; only
the turn source differs (scripted TOML vs a live agent's choices).
"""

import re
import time

from gentar.benchhost import BenchHost
from gentar.pty_driver import _KEYS, DriverAbort, PtyDriver
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
                    if turn.get("optional"):
                        # Screen never showed (claude-code's onboarding
                        # interleaves an intermittent security-notes page
                        # — probe 5 saw it in some fresh benches, not
                        # others). Skip, don't fail.
                        _ok(spans, subject, run_id, name, i,
                            f"pick /{turn['label']}/ skipped (optional)")
                        continue
                    raise TurnFailure(f"turn {i}: picker option /{turn['label']}/ not reachable")
                _ok(spans, subject, run_id, name, i, f"pick /{turn['label']}/")
            elif kind == "key":
                # Raw key events, optionally as a paced sequence. Two jobs
                # today: submitting the claude-code input box (text arrives
                # via `answer`, but its trailing \r is paste-guarded — the
                # Enter must be a SEPARATE write) and exiting it (ctrl-c
                # ctrl-c inside the ~1s window). Also the ONLY way to
                # press Enter at all: sendline's trailing \n is ignored
                # by the TUI (proven live, probe 5) — a "press enter to
                # continue" screen needs key enter, not answer send="".
                # `after` anchors the keys to a screen: a blind Enter
                # races the render and can land on the NEXT dialog's
                # default (probe 5: it pre-accepted the trust folder) —
                # the keys fire only once the pattern is on screen.
                keys = turn.get("keys") or ([turn["key"]] if turn.get("key") else [])
                if not keys:
                    raise TurnFailure(f"turn {i}: key turn needs key or keys")
                after = turn.get("after")
                if after:
                    limit = turn.get("timeout", 10 if turn.get("optional") else 60)
                    if not _await(driver, re.compile(after, re.IGNORECASE), limit):
                        if turn.get("optional"):
                            _ok(spans, subject, run_id, name, i,
                                f"key {'+'.join(keys)} skipped (optional)")
                            continue
                        raise TurnFailure(f"turn {i}: after {after!r} never appeared")
                try:
                    driver.send_keys(keys, float(turn.get("delay", 0.5)))
                except KeyError as bad:
                    raise TurnFailure(
                        f"turn {i}: unknown key {bad.args[0]!r} "
                        f"(supported: {' '.join(sorted(_KEYS))})") from None
                _ok(spans, subject, run_id, name, i, f"key {'+'.join(keys)}")
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
