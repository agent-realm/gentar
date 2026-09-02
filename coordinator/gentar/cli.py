"""gentar CLI. Exit codes: 0 pass · 1 fail · 2 usage/config error."""

import argparse

from gentar import subject_init
from gentar.config import Config
from gentar.coordinator import RunError, run
from gentar.scenarios import known_names
from gentar.toml_scenario import ScenarioError


def main() -> int:
    parser = argparse.ArgumentParser(prog="gentar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a scenario; exit code is the verdict")
    p_run.add_argument("scenario")

    sub.add_parser("ls", help="list known scenarios")

    p_subject = sub.add_parser(
        "subject", help="subject onboarding helpers")
    subject_sub = p_subject.add_subparsers(dest="subject_cmd", required=True)
    p_init = subject_sub.add_parser(
        "init", help="emit a new subject's scenario skeleton + trigger")
    p_init.add_argument("name", help="subject name: lowercase-with-dashes")
    p_init.add_argument("--repo", required=True,
                        help="subject checkout URL (recorded, never fetched)")
    p_init.add_argument("--dir", help="write the two files here instead of stdout")
    p_init.add_argument("--force", action="store_true",
                        help="with --dir: overwrite existing scaffold output")

    args = parser.parse_args()
    if args.cmd == "subject" and args.subject_cmd == "init":
        # Pure generator: no config, no bench-host, no network.
        return subject_init.emit(args.name, args.repo, args.dir or "",
                                 force=args.force)
    try:
        if args.cmd == "ls":
            for name in known_names(Config()):
                print(name)
            return 0
        return run(args.scenario)
    except (RunError, ScenarioError) as exc:
        # ScenarioError = malformed TOML in a scenarios dir (a usage
        # error, 2) — including an off-schema file that breaks `ls`.
        print(f"error: {exc}")
        return 2
