"""A driller's session: the model looks at the screen, the coordinator types.

The model never reaches the bench. Each turn the coordinator reads the
rendered screen, scrubs it, asks the model for ONE step (DrillerStep in
baml_src/drillers.baml), checks the step, and only then types it:

  - the danger gate runs on the screen before every step and on the TEXT the
    model wants typed; a match ends the session as a boundary finding, never
    a crash and never a keypress;
  - a KEY step may only name the engine's key vocabulary (gentar/keys.py);
  - a TYPE step is printable text on one line: no control characters, no
    escape sequences, no embedded newline (Enter is its own flag, sent as a
    separate write, after the danger gate looks at the screen once more);
  - budgets end the session, not the run: wall clock, steps, model calls
    and input tokens. Whatever was seen so far still becomes notes.

Then the model writes its notes (DrillerNotes). What happens to them, and
the verdict, is driller.py's: notes become typed findings, the verdict comes
from the boundary audit alone.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from gentar.gates import DANGER_RE
from gentar.keys import KEYS

# Printable, one line. Tabs are allowed (shell completion); nothing below
# 0x20 otherwise, no DEL, no C1 controls.
_UNPRINTABLE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")


class DrillBudget:
    def __init__(self, seconds: float = 900, steps: int = 60, calls: int = 80,
                 input_tokens: int = 400_000, every: float = 2.0):
        self.seconds, self.steps, self.calls = seconds, steps, calls
        self.input_tokens, self.every = input_tokens, every


@dataclass
class DrillResult:
    ended: str                      # "done", "budget: …", "danger: …", "model: …"
    steps: int
    history: list[str] = field(default_factory=list)
    notes: str = ""
    boundary: list[str] = field(default_factory=list)   # findings about the wall


def step_problem(step) -> str | None:
    """Why a model step must not be typed, or None."""
    kind = getattr(getattr(step, "kind", None), "value", str(getattr(step, "kind", "")))
    if kind == "KEY":
        key = (step.key or "").strip().lower()
        return None if key in KEYS else f"key {step.key!r} is not in the vocabulary"
    if kind == "TYPE":
        text = step.text or ""
        if not text:
            return "empty text"
        if _UNPRINTABLE.search(text):
            return "text holds a control character or a newline"
        if DANGER_RE.search(text):
            return "text matches the danger gate"
        return None
    if kind in ("WAIT", "DONE"):
        return None
    return f"unknown step kind {kind!r}"


def drill(driver, model, charter: str, brief: str, scrub, budget: DrillBudget,
          emit=lambda *a, **k: None, sleep=time.sleep, clock=time.monotonic) -> DrillResult:
    """One session. `driver` is a PtyDriver (screen/send_text/send_key/
    abort); `model` has next(charter, brief, screen, history) -> step,
    notes(charter, brief, history, screen) -> str, and `calls` /
    `input_tokens` counters. `scrub` is the run's redactor."""
    deadline = clock() + budget.seconds
    history: list[str] = []
    steps = 0
    boundary: list[str] = []
    ended = "done"
    while True:
        if clock() > deadline:
            ended = f"budget: {budget.seconds:.0f}s wall clock"
            break
        if steps >= budget.steps:
            ended = f"budget: {budget.steps} steps"
            break
        if model.calls >= budget.calls or model.input_tokens >= budget.input_tokens:
            ended = f"budget: model {model.calls} calls / {model.input_tokens} input tokens"
            break
        scr = driver.screen()
        if DANGER_RE.search(scr):
            driver.abort("a screen matching the danger gate appeared under a driller")
            boundary.append("the danger gate fired on the screen")
            ended = "danger: screen"
            break
        try:
            step = model.next(charter, brief, scrub(scr), list(history))
        except Exception as exc:                        # noqa: BLE001 — the model is outside
            ended = f"model: {type(exc).__name__}"
            break
        kind = getattr(getattr(step, "kind", None), "value", str(getattr(step, "kind", "")))
        why = scrub((getattr(step, "why", "") or "")[:200])
        problem = step_problem(step)
        if problem:
            # Refused, never typed. A dangerous command is a boundary finding
            # and ends the session; anything else is a malformed step the
            # model gets told about on its next turn.
            if "danger" in problem:
                boundary.append(f"the driller asked to type a command matching the danger gate "
                                f"({why or 'no reason given'})")
                ended = "danger: typed text"
                break
            history.append(f"REFUSED ({problem}): {why}")
            steps += 1
            sleep(budget.every)
            continue
        if kind == "DONE":
            ended = "done"
            break
        if kind == "WAIT":
            history.append(f"wait: {why}")
            sleep(budget.every)
            continue
        # The model call may have taken seconds: act on the screen as it is
        # NOW, danger gate again before any byte goes out.
        scr = driver.screen()
        if DANGER_RE.search(scr):
            driver.abort("a screen matching the danger gate appeared while the driller thought")
            boundary.append("the danger gate fired on the screen")
            ended = "danger: screen"
            break
        if kind == "KEY":
            key = step.key.strip().lower()
            driver.send_key(key)
            history.append(f"key {key}: {why}")
        else:
            driver.send_text(step.text)
            shown = scrub(step.text)
            if step.enter:
                sleep(0.3)                              # Enter as its own write
                scr = driver.screen()
                if DANGER_RE.search(scr):
                    driver.abort("a screen matching the danger gate appeared before Enter")
                    boundary.append("the danger gate fired on the screen")
                    history.append(f"typed (no Enter) {shown!r}: {why}")
                    ended = "danger: screen"
                    break
                driver.send_key("enter")
            history.append(f"typed {shown!r}{' + Enter' if step.enter else ''}: {why}")
        steps += 1
        emit("driller.step", {"step": str(steps), "kind": kind})
        sleep(budget.every)
    notes = ""
    try:
        notes = model.notes(charter, brief, list(history), scrub(driver.screen()))
    except Exception as exc:                            # noqa: BLE001
        notes = ""
        ended += f"; notes: {type(exc).__name__}"
    return DrillResult(ended=ended, steps=steps, history=history, notes=scrub(notes or ""),
                       boundary=boundary)


class BamlModel:
    """The driller model on our route: DrillerStep / DrillerNotes through
    BAML, with the model's environment passed explicitly (never the
    process environment, which holds arena keys) and usage counted."""

    def __init__(self, env: dict[str, str]):
        from baml_py import Collector
        from gentar.baml_client import b
        from gentar.driller import FORBIDDEN_ENV
        if any(k in env for k in FORBIDDEN_ENV):
            raise RuntimeError("BOUNDARY_API_KEY in the model environment")
        self._collector = Collector(name="driller")
        keys = ("GENTAR_DRILLER_MODEL_URL", "GENTAR_DRILLER_MODEL", "GENTAR_DRILLER_MODEL_KEY")
        self._b = b.with_options(collector=self._collector,
                                 env={k: env.get(k, "") for k in keys})
        self.calls = 0
        self.input_tokens = 0

    def _count(self):
        self.calls += 1
        u = getattr(self._collector.last, "usage", None) if self._collector.last else None
        self.input_tokens += int(getattr(u, "input_tokens", 0) or 0)

    def next(self, charter, brief, screen, history):
        try:
            return self._b.DrillerStep(charter, brief, screen, history)
        finally:
            self._count()

    def notes(self, charter, brief, history, screen):
        try:
            return self._b.DrillerNotes(charter, brief, history, screen)
        finally:
            self._count()
