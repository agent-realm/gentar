"""`gentar/run.sh --review [--since <ref>]`: the diff half of the review.

The names half (what the repo ships against what the suites mention) cannot
see a change INSIDE a file a suite already names. The diff half starts from
the commits instead: every changed path is listed, each suite mentioning one
is named for re-reading, and executables added, removed or changed are
called out. Driven through the real run.sh in a scratch git repo.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template"

SUITE = '''[scenario]
subject = "revsince"

[[oracle.steps]]
run = "./install.sh && bin/tool --version"
'''


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@unittest.skipUnless((KIT / "gentar" / "run.sh").exists(),
                     "needs a checkout (the kit is not in the image build context)")
class ReviewSinceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        r = self.repo = self.tmp / "repo"
        shutil.copytree(KIT / "gentar", r / "gentar")
        shutil.rmtree(r / "gentar" / "scenarios")
        (r / "gentar" / "scenarios").mkdir()
        (r / "gentar" / "scenarios" / "first-suite.toml").write_text(SUITE)
        (r / "bin").mkdir()
        self.exe(r / "install.sh")
        self.exe(r / "bin" / "tool")
        self.exe(r / "old-helper.sh")
        (r / "lib.py").write_text("x = 1\n")
        (r / "notes.txt").write_text("a\n")
        git(r, "init", "-q", "-b", "main")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "adopt")
        self.adopted = git(r, "rev-parse", "HEAD")
        # the change: a new statement inside a binary the suite names, a new
        # executable, one removed, a rename, and a file nothing mentions
        (r / "bin" / "tool").write_text("#!/bin/sh\necho new-flag\n")
        self.exe(r / "bin" / "fresh")
        (r / "old-helper.sh").unlink()
        (r / "notes.txt").rename(r / "notes.md")
        (r / "lib.py").write_text("x = 2\n")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "grow")

    @staticmethod
    def exe(p):
        p.write_text(f"#!/bin/sh\necho {p.name}\n")      # distinct: no false renames
        p.chmod(0o755)

    def review(self, *extra):
        env = dict(os.environ)
        env.pop("GENTAR_SUBJECT", None)
        return subprocess.run(["/bin/bash", "gentar/run.sh", "--review", *extra],
                              cwd=self.repo, env=env, capture_output=True, text=True)

    def test_a_change_inside_a_named_binary_is_visible(self):
        r = self.review()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        # default ref: the commit that last changed a scenario (the adoption)
        self.assertIn(f"since {self.adopted[:12]} .. HEAD", out)
        self.assertIn("last changed a scenario", out)
        self.assertIn("changed  bin/tool", out)                 # the blind spot, closed
        self.assertIn("added    bin/fresh", out)
        self.assertIn("removed  old-helper.sh", out)
        self.assertIn("R  notes.txt -> notes.md", out)
        suites = out.split("suites that mention a changed path")[1].split("changed paths no suite")[0]
        self.assertIn("first-suite.toml", suites)
        self.assertIn("bin/tool", suites)
        unmentioned = out.split("changed paths no suite mentions:")[1].split("not covered here")[0]
        for p in ("lib.py", "notes.md", "notes.txt", "old-helper.sh", "bin/fresh"):
            self.assertIn(p, unmentioned)
        self.assertNotIn("bin/tool", unmentioned)
        self.assertIn("--help output", out)                    # says what it does not do

    def test_since_an_explicit_ref(self):
        r = self.review("--since", "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("changed paths outside gentar/: 0", r.stdout)
        self.assertIn("executables:\n    (none)", r.stdout)

    def test_the_working_tree_is_not_the_diff(self):
        (self.repo / "uncommitted.sh").write_text("x\n")      # deterministic: HEAD only
        r = self.review("--since", self.adopted)
        self.assertNotIn("uncommitted.sh", r.stdout.split("changed paths outside")[1])

    def test_the_output_is_deterministic(self):
        self.assertEqual(self.review().stdout, self.review().stdout)

    def test_a_suite_without_verify_blocks_counts_zero_once(self):
        self.assertIn("first-suite.toml             0 asserted", self.review().stdout)

    def test_a_bad_or_unknown_ref_is_a_refusal(self):
        for ref, why in (("--oops", "bad ref"), ("a;rm -rf /", "bad ref"),
                         ("nosuchref", "fetch-depth: 0")):
            r = self.review("--since", ref)
            self.assertEqual(r.returncode, 2, (ref, r.stdout, r.stderr))
            self.assertIn(why, r.stderr)
        r = self.review("--since")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--since needs a ref", r.stderr)

    def test_a_broken_policy_does_not_hide_the_diff(self):
        (self.repo / "gentar" / "policy.toml").write_text("[phase1]\nbenh = 1\n")
        r = self.review()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("changed  bin/tool", r.stdout)


if __name__ == "__main__":
    unittest.main()
