"""A subject suite never hides behind a builtin's name (review A5), and an
assertion's path and text reach the bench's shell literally (review A9).

A5: `_resolve` looked in the builtin registry first, so a subject suite
named `smoke` or `smoke-fail` silently ran the engine's own self-test.
A9: assertions quoted with repr(), which switches to double quotes when the
text holds a `'`; the bench's shell then expanded `$` and backticks, and
repr's doubled backslashes no longer matched.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.asserts import check_files
from gentar.config import Config


def cfg_with(scenarios_dir):
    env = {"GENTAR_SCENARIOS_DIR": str(scenarios_dir), "GENTAR_REPORT_DIR": ""}
    with mock.patch.dict(os.environ, env, clear=True):
        return Config()


class BuiltinNameTest(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, ignore_errors=True))
        self.cfg = cfg_with(self.d)

    def test_a_subject_suite_named_like_a_builtin_is_refused(self):
        for name in ("smoke", "smoke-fail"):
            with self.subTest(name=name):
                f = self.d / f"{name}.toml"
                f.write_text(f'[scenario]\nname = "{name}"\n[oracle]\nsteps = ["true"]\n')
                with self.assertRaisesRegex(coord.RunError, "name of an engine builtin"):
                    coord._resolve(name, self.cfg)
                f.unlink()

    def test_the_name_inside_the_file_counts_too(self):
        (self.d / "mine.toml").write_text('[scenario]\nname = "smoke"\n[oracle]\nsteps = ["true"]\n')
        with self.assertRaisesRegex(coord.RunError, "rename it"):
            coord._resolve("smoke", self.cfg)

    def test_the_builtin_still_runs_when_nothing_clashes(self):
        (self.d / "other.toml").write_text('[scenario]\nname = "other"\n[oracle]\nsteps = ["true"]\n')
        (self.d / "broken.toml").write_text("[scenario\n")      # not this run's problem
        fn, scenario = coord._resolve("smoke", self.cfg)
        self.assertIsNone(scenario)
        self.assertIs(fn, coord.REGISTRY["smoke"])


class ShellBench:
    """Runs each assertion command in a real /bin/sh, as a bench would."""

    def __init__(self, cwd):
        self.cwd = cwd

    def exec(self, sandbox, command, timeout=300, env=None):
        r = subprocess.run(["/bin/sh", "-c", command], cwd=self.cwd,
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr


class QuotingTest(unittest.TestCase):

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.d, ignore_errors=True))
        self.bench = ShellBench(self.d)

    def test_text_with_a_quote_dollar_and_backticks_is_matched_literally(self):
        text = "it's $(touch canary1) `touch canary2` $HOME \\d"
        (self.d / "f.txt").write_text(f"before\n{text}\nafter\n")
        [r] = check_files(self.bench, "s", str(self.d), [{"path": str(self.d / "f.txt"),
                                                          "contains": text}])
        self.assertTrue(r.ok, r.detail)
        self.assertFalse((self.d / "canary1").exists())
        self.assertFalse((self.d / "canary2").exists())

    def test_a_path_with_a_quote(self):
        (self.d / "it's here").write_text("x")
        [r] = check_files(self.bench, "s", str(self.d), [{"path": str(self.d / "it's here")}])
        self.assertTrue(r.ok, r.detail)

    def test_only_a_leading_tilde_is_home(self):
        (self.d / "a").mkdir()
        (self.d / "a" / "x~y").write_text("x")
        [r] = check_files(self.bench, "s", str(self.d), [{"path": "~/a/x~y"}])
        self.assertTrue(r.ok, r.detail)
        self.assertEqual(r.name, f"file-exists {self.d}/a/x~y")


if __name__ == "__main__":
    unittest.main()
