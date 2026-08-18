"""gentar CLI. Exit code = verdict."""

import argparse

from gentar.coordinator import run
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
    return run(args.scenario)
