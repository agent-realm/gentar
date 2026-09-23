"""`gentar/run.sh --check` keeps the exit-code contract: 2 is a refusal.

A policy.toml with an unknown key is a configuration error; plan.py lint
refuses it with 2. --check used to fold every non-zero into 1, so a caller
could not tell a misconfigured adoption from a failing assertion (Codex).
Driven through the real run.sh in a scratch adoption, staging the engine
from this checkout.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template"


@unittest.skipUnless((KIT / "gentar" / "run.sh").exists() and (ROOT / ".git").exists(),
                     "needs a checkout (the kit is not in the image build context)")
class CheckExitTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        repo = self.tmp / "repo"
        shutil.copytree(KIT / "gentar", repo / "gentar")
        toml = repo / "gentar" / "scenarios" / "first-suite.toml"
        toml.write_text(toml.read_text().replace('"REPLACE-ME"', '"checkexit"'))
        self.repo = repo
        self.head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=True).stdout.strip()

    def check(self):
        env = dict(os.environ, GENTAR_REPO_URL=str(ROOT), GENTAR_REF=self.head,
                   GENTAR_DRYRUN_SYSTEM_DIRS=str(self.tmp / "none"))
        env.pop("CI", None)
        return subprocess.run(["/bin/bash", "gentar/run.sh", "--check"], cwd=self.repo,
                              env=env, capture_output=True, text=True)

    def test_a_policy_refusal_is_exit_2_not_1(self):
        (self.repo / "gentar" / "policy.toml").write_text("[phase1]\nbenh = \"off\"\n")
        r = self.check()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("unknown key", r.stderr)


if __name__ == "__main__":
    unittest.main()
