"""Doc claims that must stay true (ground-up review 2026-10-19, D3 and C5).

Each test pins a claim the docs make against the code it describes, so
the claim and the code move together:

- the examples work when followed: copied over the kit, an example's
  scenarios disagree with the kit's template suite on `subject`, and
  `run.sh` refuses (exit 2) until that suite is deleted, which every
  example README now says to do;
- "copy first-suite.toml under your suite's name" makes a new suite, not a
  second `first-suite` hiding the first;
- the scenario inventory lists every suite the engine ships;
- the danger gate catches what the pilot-simulator reference says it
  catches, and lets through what it says it lets through;
- the osb tier's 30-second cutoff is gentar's own pty bridge, and the docs
  say so instead of blaming the OpenSandbox server (Codex on #93).
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gentar.gates import APPROVAL_RE, DANGER_RE
from gentar.toml_scenario import TomlScenario

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
EXAMPLES = ROOT / "examples"
DOCS = ROOT / "docs"
SCENARIOS = ROOT / "coordinator" / "scenarios"


@unittest.skipUnless(KIT.exists() and EXAMPLES.exists() and shutil.which("bash"),
                     "the kit and examples/ are not in the image build context")
class ExamplesWorkWhenFollowedTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def adopt(self, example):
        repo = self.tmp / example.name
        shutil.copytree(KIT, repo / "gentar")
        shutil.copytree(example / "gentar", repo / "gentar", dirs_exist_ok=True)
        return repo

    def route(self, repo):
        # --route resolves the subject and needs no engine, Docker or bench
        env = dict(os.environ, GENTAR_LOCK_DIR=str(self.tmp))   # not /tmp
        return subprocess.run(["bash", "gentar/run.sh", "--route"], cwd=repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_an_example_runs_only_once_the_template_suite_is_gone(self):
        examples = sorted(d for d in EXAMPLES.iterdir() if (d / "gentar" / "scenarios").is_dir())
        self.assertGreaterEqual(len(examples), 9)
        for example in examples:
            with self.subTest(example=example.name):
                repo = self.adopt(example)
                left = self.route(repo)
                self.assertEqual(left.returncode, 2, left.stdout + left.stderr)
                self.assertIn("scenarios disagree on subject", left.stderr)
                (repo / "gentar" / "scenarios" / "first-suite.toml").unlink()
                gone = self.route(repo)
                self.assertEqual(gone.returncode, 0, gone.stdout + gone.stderr)

    def test_every_example_passes_the_dry_run_half_of_check(self):
        # `run.sh --check` dry-runs every suite with UNVERIFIED accepted.
        # Example 09's suite reads a secret only its mirror holds: it said
        # "--check: clean" and failed here until it declared bench_only.
        import sys
        for example in sorted(d for d in EXAMPLES.iterdir() if (d / "gentar").is_dir()):
            with self.subTest(example=example.name):
                repo = self.adopt(example)
                (repo / "gentar" / "scenarios" / "first-suite.toml").unlink()
                env = dict(os.environ, GENTAR_ENGINE=str(ROOT / "coordinator"),
                           GENTAR_DRYRUN_UNVERIFIED="ok",
                           GENTAR_DRYRUN_SYSTEM_DIRS=str(self.tmp / "none"))
                r = subprocess.run([sys.executable, "gentar/dryrun.py"], cwd=repo, env=env,
                                   capture_output=True, text=True, timeout=120)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_copy_instruction_says_to_delete_the_template_suite(self):
        said = 0
        for readme in sorted(EXAMPLES.glob("*/README.md")):
            text = readme.read_text()
            if re.search(r"[Cc]opy\b[^.]*`gentar/`", text):
                said += 1
                with self.subTest(readme=readme.parent.name):
                    self.assertIn("first-suite.toml", text)
        self.assertGreaterEqual(said, 6)
        self.assertIn("## Trying an example", (EXAMPLES / "README.md").read_text())


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class TemplateSuiteCopyTest(unittest.TestCase):

    def test_a_copy_under_a_new_file_name_is_a_new_suite(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        template = KIT / "scenarios" / "first-suite.toml"
        copy = tmp / "install-path.toml"
        shutil.copy(template, copy)
        self.assertEqual(TomlScenario(template).name, "first-suite")
        self.assertEqual(TomlScenario(copy).name, "install-path")


@unittest.skipUnless(DOCS.exists(), "docs/ is not in the image build context")
class ScenarioInventoryTest(unittest.TestCase):

    def test_every_engine_suite_is_listed_and_counted(self):
        text = (DOCS / "reference" / "scenario-inventory.md").read_text()
        listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|", text, re.MULTILINE))
        tomls = {p.stem for p in SCENARIOS.glob("*.toml")}
        builtins = {"smoke", "smoke-fail"}
        self.assertEqual(sorted(tomls | builtins), sorted(listed))
        m = re.search(r"(\d+) suites: (\d+) TOML files", text)
        self.assertIsNotNone(m)
        self.assertEqual((int(m.group(1)), int(m.group(2))),
                         (len(tomls) + len(builtins), len(tomls)))


class DangerGateClaimsTest(unittest.TestCase):
    """docs/reference/pilot-simulator.md, "The danger gate": a short list,
    a tripwire, not a sandbox. If the gate widens, the docs must say so."""

    CAUGHT = ["rm -rf /", "rm -rf /*", "mkfs.ext4 /dev/sda1", "dd if=x of=/dev/sda",
              "echo x > /dev/nvme0n1", ":(){ :|:& };:", "shutdown -h now", "poweroff",
              "systemctl reboot", "iptables -F"]
    PASSES = ["rm -rf ~", "rm -rf /home/user", "rm -rf *", "git push --force",
              "DROP TABLE users;"]

    def test_the_documented_list_matches_the_pattern(self):
        for cmd in self.CAUGHT:
            with self.subTest(caught=cmd):
                self.assertIsNotNone(DANGER_RE.search(cmd))
        for cmd in self.PASSES:
            with self.subTest(passes=cmd):
                self.assertIsNone(DANGER_RE.search(cmd))

    def test_the_approval_prompts_named_are_the_ones_recognised(self):
        for prompt in ("Do you want to proceed?", "Do you want to make this edit?",
                       "This command requires approval", "Allow this command?"):
            with self.subTest(prompt=prompt):
                self.assertIsNotNone(APPROVAL_RE.search(prompt))

    @unittest.skipUnless(DOCS.exists(), "docs/ is not in the image build context")
    def test_the_docs_say_what_passes(self):
        ref = (DOCS / "reference" / "pilot-simulator.md").read_text()
        self.assertIn("## The danger gate", ref)
        for cmd in ("rm -rf ~", "rm -rf /home/user", "rm -rf *"):
            self.assertIn(f"`{cmd}`", ref)
        self.assertIn("**`answer`, `pick` and `key` turns do not check it.**", ref)
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("aborts\n  anything destructive", readme)
        self.assertIn("`rm -rf ~` passes it", readme)


@unittest.skipUnless(DOCS.exists(), "docs/ is not in the image build context")
class OsbQuietSessionTest(unittest.TestCase):

    def test_the_cutoff_is_the_bridge_s_and_the_docs_say_so(self):
        bridge = (ROOT / "coordinator" / "gentar" / "osb_pty_bridge.py").read_text()
        [secs] = re.findall(r"ws\.recv\(timeout=(\d+)\)", bridge)
        for doc in (DOCS / "reference" / "bench-tiers.md", DOCS / "guides" / "bench-tiers.md"):
            with self.subTest(doc=doc.name, dir=doc.parent.name):
                text = " ".join(doc.read_text().split())
                self.assertIn("pty bridge", text)
                self.assertIn(f"sends nothing for {secs} seconds", text)
                self.assertNotRegex(text, r"server ends a pty session")


if __name__ == "__main__":
    unittest.main()
