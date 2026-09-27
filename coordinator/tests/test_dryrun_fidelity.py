"""The dry-run describes a bench, not the host it happens to run on.

Two gaps the first adopter hit on a GitHub-hosted runner (claude-playbooks):
prepare() ran for a suite it does not stand in for, and its build shadowed
what that suite installed; and an install landed in a writable
/usr/local/bin — outside the scratch home — where a bench (unprivileged)
could never write. Driven through the real dryrun.py with the engine's own
scenario parser, in a scratch adoption.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
ENGINE = ROOT / "coordinator"

SUITE = """[scenario]
name = "{name}"
subject = "fid"
[oracle]
steps = [{steps}]
[[verify.commands]]
command = "true"
"""

HOOKS = """
import os
SKIP_STEP_SUBSTR = ("make build",)
def prepare(env):
    with open(os.environ["PREPARE_LOG"], "a") as f:
        f.write(os.path.basename(env["WORKSPACE_DIR"]) + "\\n")
"""


class _ScratchAdoption(unittest.TestCase):
    """A scratch adoption with the kit's dryrun.py; no tests of its own."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        repo = self.tmp / "repo"
        (repo / "gentar" / "scenarios").mkdir(parents=True)
        shutil.copy(KIT / "dryrun.py", repo / "gentar" / "dryrun.py")
        self.repo = repo
        self.log = self.tmp / "prepare.log"
        self.log.touch()

    def suite(self, name, steps):
        (self.repo / "gentar" / "scenarios" / f"{name}.toml").write_text(
            SUITE.format(name=name, steps=", ".join(f'"{s}"' for s in steps)))

    def dryrun(self, *paths, **env):
        e = dict(os.environ, GENTAR_ENGINE=str(ENGINE), PREPARE_LOG=str(self.log),
                 GENTAR_DRYRUN_SYSTEM_DIRS=str(self.tmp / "nonexistent"))
        e.update(env)
        return subprocess.run([sys.executable, "gentar/dryrun.py", *paths],
                              cwd=self.repo, env=e, capture_output=True, text=True)

    def prepared_for(self):
        return len(self.log.read_text().splitlines())


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class DryrunFidelityTest(_ScratchAdoption):

    def test_prepare_runs_only_for_suites_it_stands_in_for(self):
        (self.repo / "gentar" / "hooks.py").write_text(HOOKS)
        self.suite("built", ["make build", "true"])
        self.suite("released", ["true"])      # installs a release; no build
        r = self.dryrun()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.prepared_for(), 1, "prepare() ran for a suite it does not replace")

    def test_without_skip_substrings_prepare_runs_for_every_suite(self):
        (self.repo / "gentar" / "hooks.py").write_text(
            HOOKS.replace('SKIP_STEP_SUBSTR = ("make build",)', "SKIP_STEP_SUBSTR = ()"))
        self.suite("a", ["true"])
        self.suite("b", ["true"])
        self.assertEqual(self.dryrun().returncode, 0)
        self.assertEqual(self.prepared_for(), 2)

    def test_a_writable_system_dir_warns_locally_and_refuses_in_ci(self):
        self.suite("a", ["true"])
        exposed = self.tmp / "usr-local-bin"
        exposed.mkdir()                        # writable by us, like a hosted runner's
        r = self.dryrun(GENTAR_DRYRUN_SYSTEM_DIRS=str(exposed))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARNING", r.stderr)
        self.assertIn(str(exposed), r.stderr)
        r = self.dryrun(GENTAR_DRYRUN_SYSTEM_DIRS=str(exposed), GENTAR_DRYRUN_STRICT="1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("refusing", r.stderr)


TEMPLATED = """[scenario]
name = "{name}"
subject = "fid"
template = "{tpl}"
[oracle]
steps = ["{step}"]
[[verify.commands]]
command = "true"
"""


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class TemplateStagingTest(_ScratchAdoption):
    """A suite whose bench template supplies a tool this host lacks is
    UNVERIFIED — naming the template — unless the repo's stager installs
    the REAL tool; a stager that raises is broken, not unverified."""

    def templated(self, tpl="tool-bench-v1", step="mytool"):
        (self.repo / "gentar" / "scenarios" / "needs-tool.toml").write_text(
            TEMPLATED.format(name="needs-tool", tpl=tpl, step=step))

    def hooks(self, body):
        (self.repo / "gentar" / "hooks.py").write_text(body)

    def test_declared_without_a_stager_is_unverified_and_named(self):
        self.hooks('TEMPLATES = {"tool-bench-v1": None}\n')
        self.templated()
        r = self.dryrun()
        self.assertEqual(r.returncode, 1, r.stdout)       # not proven
        self.assertIn("UNVERIFIED (template tool-bench-v1", r.stdout)
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")    # what --check sets
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_stager_that_cannot_is_unverified(self):
        self.hooks('TEMPLATES = {"tool-bench-v1": lambda env: False}\n')
        self.templated()
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 0)
        self.assertIn("UNVERIFIED", r.stdout)

    def test_a_stager_that_installs_the_tool_makes_the_suite_run(self):
        self.hooks(
            "import os\n"
            "def stage(env):\n"
            "    b = os.path.join(env['HOME'], '.local/bin/mytool')\n"
            "    open(b, 'w').write('#!/bin/sh\\nexit 0\\n'); os.chmod(b, 0o755)\n"
            "    return True\n"
            'TEMPLATES = {"tool-bench-v1": stage}\n')
        self.templated()
        r = self.dryrun()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL PASS", r.stdout)

    def test_a_stager_that_raises_is_a_failure_even_under_check(self):
        self.hooks("def stage(env):\n    raise RuntimeError('boom')\n"
                   'TEMPLATES = {"tool-bench-v1": stage}\n')
        self.templated()
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILURE (stager for template tool-bench-v1 raised)", r.stdout)
        self.assertIn("boom", r.stdout)

    def test_an_undeclared_template_runs_as_before(self):
        self.templated(tpl="plain-bench-v1", step="true")
        r = self.dryrun()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ALL PASS", r.stdout)


if __name__ == "__main__":
    unittest.main()


GOAL_SUITE = """[scenario]
name = "{name}"
subject = "fid"
data = "synthetic"
[driver]
command = "sh -c 'read x; read y'"
goal = "Do the thing."
[[driver.actions]]
id = "go"
key = "enter"
when = "always"
[[verify.commands]]
command = "false"
"""

JUDGED_SUITE = """[scenario]
name = "{name}"
subject = "fid"
data = "synthetic"
[driver]
command = "sh -c 'echo ready; sleep 1'"
[[driver.turns]]
type = "expect"
[driver.turns.judge]
question = "Does `screen` say ready?"
"""


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class SemanticSuitesInTheDryRunTest(_ScratchAdoption):
    """claude-playbooks' first goal pilot hung run.sh --check: the dry run
    started the driver of a suite with no turns and waited forever."""

    def write(self, name, text):
        (self.repo / "gentar" / "scenarios" / f"{name}.toml").write_text(text.format(name=name))

    def test_a_goal_pilot_is_unverified_and_never_started(self):
        self.write("goal", GOAL_SUITE)
        try:
            r = subprocess.run([sys.executable, "gentar/dryrun.py", "gentar/scenarios/goal.toml"],
                               cwd=self.repo, capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, GENTAR_ENGINE=str(ENGINE),
                                        GENTAR_DRYRUN_SYSTEM_DIRS=str(self.tmp / "none")))
        except subprocess.TimeoutExpired:
            self.fail("the dry run started the goal pilot's driver and hung")
        self.assertIn("UNVERIFIED", r.stdout, r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0)          # not proven is not a pass
        self.assertNotIn("verify 0 FAIL", r.stdout)   # nothing driven, nothing verified
        ok = self.dryrun("gentar/scenarios/goal.toml", GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)   # run.sh --check

    def test_a_judged_expect_is_unverified_not_a_crash(self):
        self.write("judged", JUDGED_SUITE)
        r = self.dryrun("gentar/scenarios/judged.toml")
        self.assertNotIn("Traceback", r.stderr, r.stderr)
        self.assertIn("UNVERIFIED", r.stdout, r.stdout + r.stderr)
