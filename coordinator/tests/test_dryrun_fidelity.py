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


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class DryrunFidelityTest(unittest.TestCase):

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


if __name__ == "__main__":
    unittest.main()
