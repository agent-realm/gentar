"""gentar CLI. Exit codes: 0 pass · 1 fail · 2 usage/config error."""

import argparse

from gentar.config import Config
from gentar.coordinator import RunError, run
from gentar.scenarios import known_names


def main() -> int:
    parser = argparse.ArgumentParser(prog="gentar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a scenario; exit code is the verdict")
    p_run.add_argument("scenario")

    sub.add_parser("ls", help="list known scenarios")

    args = parser.parse_args()
    if args.cmd == "ls":
        try:
            names = known_names(Config())
        except ValueError as exc:
            print(f"error: {exc}")
            return 2
        for name in names:
            print(name)
        return 0
    try:
        return run(args.scenario)
    except (RunError, ValueError) as exc:
        # ValueError = off-shape config value (e.g. GENTAR_NAME_PREFIX) —
        # a usage error (2), never a traceback.
        print(f"error: {exc}")
        return 2
