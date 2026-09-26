"""Scripted driver turns — applies a scenario's [driver] block to the
pty: answer prompts, expect patterns, navigate pickers, and prove the
danger gate fires. The same PtyDriver serves the agent adapters; only
the turn source differs (scripted TOML vs a live agent's choices).
"""

import os
import re
import time

from gentar.benchhost import BenchHost
from gentar.pty_driver import _KEYS, APPROVAL_RE, DANGER_RE, DriverAbort, PtyDriver, _tail
from gentar.spans import Spans


class TurnFailure(AssertionError):
    pass


def run_turns(scenario, bench: BenchHost, run_id: str, spans: Spans,
              subject: str = "arena",
              env: dict[str, str] | None = None,
              report=None) -> str:
    name = scenario.name
    judge = None
    if getattr(scenario, "uses_judge", False):
        # The coordinator already refused a non-synthetic scenario or a
        # missing key before any bench existed; Judge re-checks both.
        from gentar.judge import KEY_NAME, Judge
        judge = Judge(scenario, os.environ.get(KEY_NAME, ""), spans.redactor.scrub,
                      spans, subject, run_id,
                      max_calls=scenario.judge_max_calls,
                      max_input_tokens=scenario.judge_max_input_tokens,
                      lines=scenario.judge_lines)
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
            elif kind == "expect" and "judge" in turn:
                verdict = _judged(driver, judge, turn, i)
                _ok(spans, subject, run_id, name, i, verdict)
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
        # covers the tail of a scripted one. A TUI that never exits is
        # NOT a pass: the file may exist while the interactive exit
        # (e.g. the ctrl-c pair) silently failed, and close() below
        # would mask that with a force kill — fail honestly instead
        # (PR #26 review).
        if not driver.wait_done(300):
            raise TurnFailure(
                "driver command never exited after the final turn "
                "(wait_done 300s) — the scripted exit keys did not "
                "produce EOF")
        return f"driver ok: {len(scenario.turns)} turns"
    finally:
        spans.emit(subject, run_id, name, "driver.transcript",
                   detail=driver.transcript[-8000:])
        if report is not None:
            report.transcript = driver.transcript
        driver.close()


def _judged(driver: PtyDriver, judge, turn: dict, i: int, sleep=time.sleep) -> str:
    """A semantic expect: poll the screen until the judge says yes with
    P(yes) >= p_min on `hold` consecutive polls. Never presses anything —
    unlike a regex expect, it does not auto-approve ordinary prompts — and
    the deterministic danger gate is checked on every poll, before the
    judge is asked. A timeout fails, naming the last P(yes) and whether it
    was a clear no (<= p_max_no) or undecided."""
    from gentar.judge import JudgeUnavailable
    j = turn["judge"]
    p_min, p_no = float(j.get("p_min", 0.9)), float(j.get("p_max_no", 0.2))
    hold, every = int(j.get("hold", 2)), float(j.get("every", 3))
    limit = float(turn.get("timeout", 90))
    waited, streak, p = 0.0, 0, None
    while True:
        scr = driver.screen()
        if APPROVAL_RE.search(scr) and DANGER_RE.search(scr):
            driver.abort("a prompt matching the danger gate appeared during a judged turn")
            raise DriverAbort("danger gate: " + _tail(scr, 300))
        try:
            p = judge.noul(scr, j["question"], true=j.get("true", ""),
                           false=j.get("false", ""), turn=str(i))
        except JudgeUnavailable as exc:
            raise TurnFailure(f"turn {i}: judge unavailable — {exc}") from None
        streak = streak + 1 if p >= p_min else 0
        if streak >= hold:
            return f"judge yes (P={p:.2f}, held {hold}) {j['question'][:80]!r}"
        if waited >= limit:
            band = "a clear no" if p <= p_no else "undecided"
            raise TurnFailure(
                f"turn {i}: judge never held yes within {limit:.0f}s — last "
                f"P(yes)={p:.2f} ({band}; needs >= {p_min} x{hold}): {j['question'][:120]!r}")
        sleep(every)
        waited += every


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
