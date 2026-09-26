"""What a goal pilot may be offered, and how it is asked — no pexpect.

Shared by the pilot (scripted.py) and bin/judge-eval, so a fixture is
judged with exactly the question and the options a run would ask.
"""

import re

from gentar.gates import APPROVAL_RE, DANGER_RE

GOAL_RESERVED = {
    "wait": "nothing useful can be done yet: the screen is still loading or changing",
    "done": "the goal is achieved: the screen shows it complete",
    "stuck": "no offered action can advance the goal from this screen",
}
_LOW = 0.4          # below this, the top pick is not even a lean


def _answers_approval(action: dict) -> bool:
    """Would this action answer an approval prompt (y / yes / Enter)?"""
    return (str(action.get("send", "")).strip().lower() in ("y", "yes")
            or action.get("key") == "enter" or action.get("then") == "enter")


def goal_offer(actions: list, screen: str) -> dict:
    """The actions the judge may pick on THIS screen (id -> when), plus
    wait / done / stuck. Approval is explicit and narrow: on an approval
    screen only a declared approving action whose `on` anchors this very
    screen is offered, and no other action that would answer the prompt;
    an approving action is never offered off its anchor."""
    approval = bool(APPROVAL_RE.search(screen))
    out = {}
    for a in actions:
        if a.get("approve"):
            if re.search(a["on"], screen, re.IGNORECASE | re.MULTILINE) and not DANGER_RE.search(screen):
                out[a["id"]] = a["when"]
        elif approval and _answers_approval(a):
            continue
        else:
            out[a["id"]] = a["when"]
    out.update(GOAL_RESERVED)
    return out


_SPIN = re.compile(r"[✻✽✢·✳✶⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏|/\\-]|\d")


def screen_key(screen: str) -> str:
    """What the loop guard compares: the prepared screen with spinner glyphs
    and digits removed, so a spinner or a clock cannot make one stuck screen
    look new on every poll."""
    import hashlib
    from gentar.judge import prepare_screen
    return hashlib.sha256(_SPIN.sub("", prepare_screen(screen, 40)).encode()).hexdigest()


def goal_instructions(goal: str) -> str:
    """The Choice question a goal pilot asks on every poll. The goal is in
    the instructions, not the state, so screen text cannot restate it."""
    return (f"Goal: {goal}\n"
            "`screen` is a terminal. Pick the ONE option that best advances the goal "
            "from this exact screen, as it is now.")
