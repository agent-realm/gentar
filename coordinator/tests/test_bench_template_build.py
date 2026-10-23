"""bench-template/build.sh works the way its header says to run it.

The header said `ssh bench-host 'sh -s' < bench-template/build.sh`, and the
script read `$(cat VERSION)` from the bench-host's working directory, where
no VERSION exists: under `set -e` it stopped there (ground-up review B4).
The pin now travels as the first argument. Driven against a stub `sbx`
that only logs its arguments, so nothing is built.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "bench-template" / "build.sh"
PIN = (ROOT / "bench-template" / "VERSION").read_text().strip() if BUILD.exists() else ""

SBX_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$SBX_LOG"
"""


@unittest.skipUnless(BUILD.exists(), "bench-template/ is not in the image build context")
class BenchTemplateBuildTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "sbx").write_text(SBX_STUB)
        (bindir / "sbx").chmod(0o755)
        self.log = self.tmp / "sbx.log"
        self.env = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", SBX_LOG=str(self.log),
                        GENTAR_TEMPLATE_WS=str(self.tmp / "ws"))
        self.home = self.tmp / "home"          # a bench-host cwd: no VERSION here
        self.home.mkdir()

    def piped(self, *args):
        """`ssh bench-host sh -s -- ARGS < bench-template/build.sh`, minus ssh."""
        with open(BUILD) as script:
            return subprocess.run(["sh", "-s", "--", *args], stdin=script, cwd=self.home,
                                  env=self.env, capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_the_documented_pipe_builds_the_pinned_version(self):
        self.assertIn('sh -s -- "$(cat bench-template/VERSION)" < bench-template/build.sh',
                      BUILD.read_text())
        r = self.piped(PIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"@anthropic-ai/claude-code@{PIN}", self.calls())
        self.assertIn("template save gentar-tpl-build gentar-bench-v1", self.calls())

    def test_piped_without_the_pin_refuses_before_any_sbx_call(self):
        r = self.piped()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("pass it as the first argument", r.stderr)
        self.assertEqual(self.calls(), "")

    def test_a_copy_of_the_directory_reads_its_version_file(self):
        copy = self.tmp / "bench-template"
        shutil.copytree(BUILD.parent, copy)
        r = subprocess.run(["sh", "build.sh"], cwd=copy, env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"@anthropic-ai/claude-code@{PIN}", self.calls())

    def test_a_hostile_version_is_refused(self):
        r = self.piped("1.0; touch /tmp/x")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.calls(), "")


if __name__ == "__main__":
    unittest.main()
