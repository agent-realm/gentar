"""This repo's dry-run hooks — the only part of the dry-run that is yours.

gentar/dryrun.py is the kit's file and stays byte-identical to the pinned
engine's copy (`gentar/run.sh --check` compares), so everything a subject
needs to adapt lives here. Any name left out keeps dryrun.py's default.
REPO below is the checkout, for a prepare() that builds from it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Steps whose substring appears here are skipped verbatim (prepare()
# already did the equivalent locally). Example: ("docker build",).
SKIP_STEP_SUBSTR = ()

# Executables that must NEVER be found on your real PATH while a suite
# runs. Two reasons to list one:
#   - your suites CREATE it (a launcher, an alias binary), so finding
#     the installed copy would let a broken install pass;
#   - your code CALLS it and a bench does not have it, so finding it here
#     would let a suite pass that fails on the bench. (claude-playbooks'
#     CLI runs `pilot` on every create; benches have no `pilot`.)
# Anything prepare() installs into the scratch ~/.local/bin is hidden
# automatically; list only what it does not. Example: ("cpb", "pilot").
HIDE_FROM_PATH = ()


def prepare(env: dict) -> None:
    """Build/stage whatever ONE suite needs, in that suite's fresh home.

    Runs once PER SUITE, not once per sweep: every suite gets its own
    scratch home and workspace, as every scenario gets its own bench. If
    your scenarios assume a built binary or generated fixtures, do it
    here (REPO is the checkout; env["HOME"] is this suite's scratch home;
    env["WORKSPACE_DIR"] its staged checkout). Put the subject's own
    binaries in env["HOME"] + "/.local/bin": whatever lands there is
    hidden from the real PATH for the suite (see sealed_path). Expensive
    builds should cache outside HOME and copy in — `go build` and most
    compilers already cache on their own.
    """
    return None
