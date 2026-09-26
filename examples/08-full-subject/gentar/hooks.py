"""This repo's dry-run hooks (see the kit's hooks.py for every option)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SKIP_STEP_SUBSTR = ()
HIDE_FROM_PATH = ("example",)   # the suites create it: never find an installed copy
TEMPLATES = {}


def prepare(env: dict) -> None:
    return None
