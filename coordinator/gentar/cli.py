"""gentar CLI. Exit codes: 0 pass · 1 fail · 2 usage/config error."""

import argparse

from gentar.coordinator import RunError, run
from gentar.scenarios import REGISTRY


def main() -> int:
    parser = argparse.ArgumentParser(prog="gentar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a scenario; exit code is the verdict")
    p_run.add_argument("scenario")

    sub.add_parser("ls", help="list known scenarios")

    args = parser.parse_args()
    if args.cmd == "ls":
        for name in sorted(REGISTRY):
            print(name)
        return 0
    try:
        return run(args.scenario)
    except RunError as exc:
        print(f"error: {exc}")
        return 2
