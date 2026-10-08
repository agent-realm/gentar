#!/usr/bin/env python3
"""route: which of this mirror's secrets the bench job may hand to a commit.

    python3 route.py <public checkout>/gentar/policy.toml "<allowed names>"

Part of the gentar kit (subject-template/mirror/arena/). The mirror's own
code: it reads the public repository's policy as DATA and runs none of its
code. A commit's policy names the secrets its suites want ([secrets]
route); the mirror's variable GENTAR_ROUTE_ALLOW names the ones it is
willing to give. A slot gets a name only when both say so, so a commit can
narrow what it receives and never widen it. A branch that edits its own
policy (or its plan.py) reaches nothing the mirror did not allow.

Slot n stays the n-th name of the commit's policy, or empty: run.sh at that
commit maps slots to names by its policy's order, so a name dropped here
must leave a hole, not shift the rest onto the wrong names.

Output: route_1= .. route_8= lines on stdout (names, never values), also
appended to $GITHUB_OUTPUT when set; dropped names noted on stderr.
Exit: 0 · 2 a policy or allowlist that is not what it should be.
"""
import os
import re
import shutil
import sys

if sys.version_info < (3, 11):               # no tomllib: a newer python, or tomli
    for candidate in ("python3.14", "python3.13", "python3.12", "python3.11"):
        if shutil.which(candidate):
            os.execvp(candidate, [candidate, os.path.abspath(__file__), *sys.argv[1:]])
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        print("route.py needs python 3.11+, or tomli", file=sys.stderr)
        sys.exit(2)
else:
    import tomllib

SLOTS = 8
NAME = re.compile(r"[A-Z][A-Z0-9_]*")
# Never routable, whatever the allowlist says: the arena's own and the
# platform's (a mistyped allowlist must not hand them out).
NEVER = ("GENTAR_", "GITHUB_", "ACTIONS_", "RUNNER_")
NEVER_NAMES = {"BENCH_SSH_KEY"}


def refuse(msg):
    print(f"route: {msg}", file=sys.stderr)
    sys.exit(2)


def main(argv):
    if len(argv) != 3:
        refuse("usage: route.py <policy.toml> \"<allowed names>\"")
    policy, allow_text = argv[1], argv[2]
    allowed = allow_text.split()
    for n in allowed:
        if not NAME.fullmatch(n) or n in NEVER_NAMES or n.startswith(NEVER):
            refuse(f"GENTAR_ROUTE_ALLOW holds {n[:60]!r}, which may not be routed")
    wanted = []
    if os.path.exists(policy):
        try:
            with open(policy, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            refuse(f"the commit's policy.toml is not valid TOML: {exc}")
        wanted = (data.get("secrets") or {}).get("route") or []
        if not isinstance(wanted, list) or not all(isinstance(n, str) for n in wanted):
            refuse("the commit's [secrets] route is not a list of names")
        if len(wanted) > SLOTS:
            refuse(f"the commit's [secrets] route names {len(wanted)} secrets; there are {SLOTS} slots")
    lines, dropped = [], []
    for i in range(SLOTS):
        n = wanted[i] if i < len(wanted) else ""
        if n and n not in allowed:
            dropped.append(n)
            n = ""
        lines.append(f"route_{i + 1}={n}")
    if dropped:
        print("route: not allowed by this mirror (GENTAR_ROUTE_ALLOW), so not routed: "
              + " ".join(d[:60] for d in dropped), file=sys.stderr)
    out = "\n".join(lines) + "\n"
    sys.stdout.write(out)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
