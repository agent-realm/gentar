"""Scripted driver turns — applies a scenario's [driver] block to the
pty: answer prompts, expect patterns, navigate pickers, and prove the
danger gate fires. The same PtyDriver serves the agent adapters; only
the turn source differs (scripted TOML vs a live agent's choices).
"""

import os
import re
import time

from gentar.benchhost import BenchHost
from gentar.goal import _LOW, GOAL_RESERVED, goal_instructions, goal_offer, screen_key  # noqa: F401
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
        if getattr(scenario, "goal", ""):
            return _goal_pilot(driver, judge, scenario, spans, subject, run_id)
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


def _goal_pilot(driver: PtyDriver, judge, sc, spans, subject, run_id,
                sleep=time.sleep, clock=time.monotonic) -> str:
    """Drive toward a goal over a closed action set. Each poll: danger gate
    first (a match anywhere aborts), then ONE Choice over what may be
    offered on this screen. An action is taken only when the same pick
    reaches p_act on two consecutive polls (identical requests can get
    different answers); `wait` waits, `stuck` fails, `done` stops driving —
    it is not a verdict, [[verify.*]] is. A step cap, a timeout and a loop
    guard (the same screen and pick three times) bound it."""
    by_id = {a["id"]: a for a in sc.actions}
    instructions = goal_instructions(sc.goal)
    deadline = clock() + float(sc.goal_timeout)
    steps, pending, low, seen, log = 0, None, 0, {}, []
    while True:
        if clock() > deadline:
            raise TurnFailure(f"goal: not reached within {sc.goal_timeout}s after {steps} action(s): "
                              f"{' → '.join(log) or 'none'}")
        scr = driver.screen()
        if DANGER_RE.search(scr):
            driver.abort("a screen matching the danger gate appeared under the goal pilot")
            raise DriverAbort("danger gate: " + _tail(scr, 300))
        offered = goal_offer(sc.actions, scr)
        from gentar.judge import JudgeUnavailable
        try:
            pick, probs, _ = judge.choose(scr, instructions, offered, turn=f"goal.{steps}")
        except JudgeUnavailable as exc:
            raise TurnFailure(f"goal: judge unavailable — {exc}") from None
        p = probs.get(pick, 0.0)
        if pick not in offered or p < float(sc.p_act):
            pending = None
            # A pick outside the offer is no pick at all, however sure.
            low = low + 1 if (pick not in offered or p < _LOW) else 0
            if low >= 3:
                raise TurnFailure(f"goal: no confident action on 3 polls running (last {pick!r} "
                                  f"p={p:.2f}) after {' → '.join(log) or 'none'}")
            sleep(float(sc.goal_every))
            continue
        low = 0
        if pending != pick:                     # confirm on the next poll
            pending = pick
            sleep(float(sc.goal_every))
            continue
        pending = None
        spans.emit(subject, run_id, sc.name, "driver.goal",
                   attrs={"step": str(steps), "pick": pick, "p": f"{p:.2f}"})
        if pick == "wait":
            sleep(float(sc.goal_every))
            continue
        if pick == "done":
            return f"goal done after {steps} action(s): {' → '.join(log) or 'none'}"
        if pick == "stuck":
            raise TurnFailure(f"goal: the judge is stuck after {' → '.join(log) or 'no action'}")
        # The judge call may have taken seconds (retries): act on the screen
        # as it is NOW. Danger gate again, and the pick must still be offered
        # on the fresh screen — else it is not acted on (Codex review).
        scr = driver.screen()
        if DANGER_RE.search(scr):
            driver.abort("a screen matching the danger gate appeared while the judge answered")
            raise DriverAbort("danger gate: " + _tail(scr, 300))
        if pick not in goal_offer(sc.actions, scr):
            sleep(float(sc.goal_every))
            continue
        if steps >= int(sc.max_steps):
            raise TurnFailure(f"goal: max_steps {sc.max_steps} reached: {' → '.join(log)}")
        key = (screen_key(scr), pick)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            raise TurnFailure(f"goal: loop — {pick!r} on the same screen three times")
        a = by_id[pick]
        if "send" in a:
            driver.send_text(a["send"])
        else:
            driver.send_key(a["key"])
        if a.get("then") == "enter":
            sleep(0.3)                          # Enter as its own write (paste guard)
            # The screen may have changed since the check: the danger gate
            # again, before the second keypress (agy review).
            scr2 = driver.screen()
            if DANGER_RE.search(scr2):
                driver.abort("a screen matching the danger gate appeared before Enter")
                raise DriverAbort("danger gate: " + _tail(scr2, 300))
            driver.send_key("enter")
        steps += 1
        log.append(pick)
        sleep(float(sc.goal_every))


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
