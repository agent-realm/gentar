"""A commit-sha check must not depend on the locale.

`case "$SHA" in *[!0-9a-f]*)` uses a bracket RANGE, and a shell that orders
ranges by the locale's collation (macOS's /bin/bash 3.2 under en_US.UTF-8
sorts a A b B ... f) lets uppercase A-E through `a-f`. test_verify_ref
failed intermittently on macOS for that reason: its random sha, uppercased,
passed whenever it held no F (2026-10-23). The kit's checks now spell the
sixteen digits out.
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKED = [
    ROOT / "subject-template" / "gentar" / "mirror.sh",
    ROOT / "subject-template" / "gentar" / "release-gate.sh",
    ROOT / "subject-template" / "mirror" / "arena" / "verify-ref.sh",
    ROOT / "bin" / "bench-reap",
]
# Uppercase, only letters A-E: inside `a-f` when ranges follow collation.
UPPER = "ABCDE0123456789ABCDE0123456789ABCDE01234"


@unittest.skipUnless(all(p.exists() for p in CHECKED), "the kit is not in the image build context")
class HexChecksTest(unittest.TestCase):

    def test_no_hex_range_in_the_shell_checks(self):
        for p in CHECKED:
            with self.subTest(f=p.name):
                self.assertNotRegex(p.read_text(), r"\[!?(?:0-9a-f|a-f0-9|0-9a-fA-F)\]")

    def run_sh(self, *argv, **env):
        e = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", **env}
        return subprocess.run(["/bin/bash", *map(str, argv)], capture_output=True, text=True,
                              env=e, cwd=ROOT, timeout=60)

    def test_an_uppercase_sha_is_a_usage_refusal_in_a_utf8_locale(self):
        r = self.run_sh(CHECKED[2], "https://example.invalid/repo.git", UPPER)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a lowercase hex commit sha", r.stderr)
        r = self.run_sh(CHECKED[1], UPPER, GITHUB_REPOSITORY="owner/repo")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
