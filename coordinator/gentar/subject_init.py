"""`gentar subject init` — the subject scaffold generator.

"Any component becomes a subject with minimal moves", made mechanical.
One command emits everything a new subject's author contributes — the
two moves of the three-move contract that live in THEIR repo:

  1. a decision-TOML scenario skeleton: subject prefilled, the install
     decision shaped as `[oracle]` steps, the budget block present,
     verify probes left as TODO stubs to fill;
  2. the trigger workflow: the exact subject-side job documented in
     docs/subject-integration.md, line for line — the emitted snippet
     IS the documented dispatch contract.

Pure generator by design: no network (nothing is fetched from
--repo), no auto-discovery of install decisions (that is agent work,
deferred), no commits to any repo. Emits to stdout; `--dir` writes
the two files instead. A verify probe left as the stub value "TODO"
makes `coordinator run` refuse with exit 2 before any bench exists
(stub guard in coordinator.run) — an honest scaffold, never a
fake-green one.
"""

import re
import sys
from pathlib import Path

# The trigger contract, VERBATIM from docs/subject-integration.md
# ("The subject-side job (GitHub shape)"). The docs-honesty-gentar
# suite anchors this constant to that doc; editing either side
# without the other is drift and fails the gate.
TRIGGER_YML = """\
# .github/workflows/gentar.yml in the SUBJECT repo
name: gentar
on:
  pull_request:
  workflow_dispatch:
    inputs:
      ref:
        description: gentar ref to test against
        default: ""
jobs:
  arena:
    runs-on: ubuntu-latest
    steps:
      - name: dispatch gentar
        run: |
          curl -fsSL -X POST \\
            -H "Authorization: Bearer ${{ secrets.GENTAR_DISPATCH_TOKEN }}" \\
            -H "Accept: application/vnd.github+json" \\
            https://api.github.com/repos/agent-realm/gentar/actions/workflows/gentar.yml/dispatches \\
            -d '{"ref":"main","inputs":{"scenario":"'"${{ github.event.inputs.ref }}"'"}}'
"""

# A subject name is one path segment: lowercase-with-dashes (it names
# the dir under the subjects root). Two dashes in a row are reserved
# elsewhere in gentar naming; keep them out of subject names too.
# Length cap 64: a name this long already overflows some filesystems'
# filename limits once "-install.toml" is appended (d3-abuser drill hit
# a traceback at 301 chars) — refuse it as a usage error instead.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_NAME_MAX = 64


def _usage_error(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def scenario_toml(name: str, repo: str) -> str:
    """The decision-TOML skeleton for subject `name` at `repo`."""
    suite = f"{name}-install"
    return f"""\
# Subject: {name} ({repo})
# Scaffolded by `gentar subject init {name} --repo {repo}`.
# You fill in exactly two things; the arena owns everything else:
#   1. [oracle] steps — your documented install decision (the subject
#      checkout is delivered to $WORKSPACE_DIR before they run);
#   2. [[verify.*]] probes — one reality assertion per claim.
# Any probe still carrying the stub value "TODO" makes
# `coordinator run {suite}` refuse with exit 2 before any bench
# exists. Fill the stubs, then run. Verdicts come from reality.
# Honesty limit (yours, not the arena's): each probe is checked against
# reality, but the arena cannot force a probe to be ABOUT your subject —
# `echo ok` asserting "ok" passes. Write probes that fail if your
# install did not happen, not probes the bench satisfies on its own.

[scenario]
name = "{suite}"
subject = "{name}"
agent = "shell"
# template = "gentar-bench-v1"   # uncomment when the install needs a bench toolchain
# credentials = ["ANTHROPIC_API_KEY"]   # only for agent-in-the-loop suites

[oracle]
steps = [
  'cd "$WORKSPACE_DIR" && ./install.sh',  # the install decision: your documented install path
]

[budget]
# Spend ceiling in spend units (tokens); 0 = unbudgeted. The budget
# guard refuses (exit 2) a run that would cross GENTAR_BUDGET_CAP.
tokens = 0

[[verify.files]]
path = "TODO"          # a file the install must leave behind, e.g. "~/.config/{name}/config.toml"
# contains = "TODO"    # optional substring the file must carry

[[verify.commands]]
command = "TODO"       # a command proving the install from reality, e.g. "{name} --version"
contains = "TODO"      # substring its output must carry
"""


def emit(name: str, repo: str, out_dir: str = "", force: bool = False) -> int:
    """Print (or, with --dir, write) the scenario TOML + the trigger.

    s4 hardening (d3-abuser drill): --dir never silently overwrites —
    an existing target file is a usage error unless --force. Every
    filesystem failure (un-creatable path, name too long for the
    filesystem) is a clean usage error naming the path, never a
    traceback.
    """
    if not _NAME_RE.match(name):
        return _usage_error(
            f"subject name {name!r} must be lowercase-with-dashes "
            f"(it names the dir under the subjects root)")
    if len(name) > _NAME_MAX:
        return _usage_error(
            f"subject name is {len(name)} chars; max {_NAME_MAX} "
            f"(filesystem limits bite once '-install.toml' is appended)")
    if not repo or any(ch.isspace() for ch in repo):
        return _usage_error(
            "--repo must be a non-empty checkout URL (no network is "
            "used; it is recorded in the emitted skeleton's header)")

    toml = scenario_toml(name, repo)
    toml_path = f"{name}-install.toml"

    if out_dir:
        root = Path(out_dir)
        targets = [root / toml_path, root / "gentar.yml"]
        try:
            root.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            return _usage_error(f"--dir {out_dir!r} cannot be created: {exc}")
        if not force:
            existing = [str(t) for t in targets if t.exists()]
            if existing:
                return _usage_error(
                    f"--dir already holds scaffold output: {', '.join(existing)} "
                    f"— pass --force to overwrite")
        # s6 hardening (d2-abuser drill): --force must not follow a
        # pre-planted symlink out of the declared dir — writes are
        # bounded to the two real paths or they refuse.
        linked = [str(t) for t in targets if t.is_symlink()]
        if linked:
            return _usage_error(
                f"--dir target is a symlink: {', '.join(linked)} — refusing "
                f"to write through it (bytes would land outside the "
                f"declared dir); replace the symlink with a real file "
                f"first")
        try:
            (root / toml_path).write_text(toml)
            (root / "gentar.yml").write_text(TRIGGER_YML)
        except (OSError, ValueError) as exc:
            return _usage_error(f"cannot write into --dir {out_dir!r}: {exc}")
        print(f"# wrote {root / toml_path}")
        print(f"# wrote {root / 'gentar.yml'}")
        print(f"# -> carry the TOML in {repo} under gentar/ (or PR it "
              f"into coordinator/scenarios/); put gentar.yml at "
              f".github/workflows/gentar.yml. To run it before it lands "
              f"in a repo (mount the dir, then point the coordinator at "
              f"the mount — a bare GENTAR_SCENARIOS_DIR=x shell prefix "
              f"never reaches the container, and inside compose --dir "
              f"sees the CONTAINER filesystem):")
        print(f"# docker compose run --rm -v \"$PWD/{name}-scaffold\":/extra:ro "
              f"-e GENTAR_SCENARIOS_DIR=/extra coordinator run {name}-install")
        return 0

    print(f"# ==== 1/2 scenario: {toml_path} — carry in the subject repo "
          f"under gentar/, or PR into gentar/coordinator/scenarios/ ====")
    print(toml, end="")
    print(f"# ==== 2/2 trigger: .github/workflows/gentar.yml in {name}'s "
          f"repo — the documented dispatch contract, line for line ====")
    print(TRIGGER_YML, end="")
    return 0
