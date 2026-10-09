"""Every kit file a subject copies byte for byte says its license.

2026-10-10 (AK47's ruling on the Apache-2.0 relicense, gentar#73): the kit's
files are redistributed verbatim into subject repositories, and Apache-2.0
asks that the license travel with them. Each carries a two-line header in
its own comment syntax, right after a shebang when there is one.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"
HEADER = ["# SPDX-License-Identifier: Apache-2.0", "# Copyright 2026 Ramazan Polat"]


def kit_files():
    spec = importlib.util.spec_from_file_location("gentar_plan_license", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = set(mod.KIT_FILES.values())
    files |= {str(p.relative_to(ROOT)) for p in (ROOT / "subject-template" / "mirror").rglob("*")
              if p.is_file() and p.suffix in (".sh", ".py", ".yml", ".yaml")}
    return sorted(files)


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class KitLicenseHeaderTest(unittest.TestCase):

    def test_every_kit_file_carries_the_header(self):
        files = kit_files()
        self.assertGreaterEqual(len(files), 5)
        for f in files:
            p = ROOT / f
            if not p.exists():
                continue                      # an optional file this tree does not ship
            lines = p.read_text().splitlines()
            start = 1 if lines and lines[0].startswith("#!") else 0
            with self.subTest(file=f):
                self.assertEqual(lines[start:start + 2], HEADER)

    def test_the_repository_license_is_apache_2(self):
        self.assertIn("Apache License", (ROOT / "LICENSE").read_text()[:200])
        self.assertTrue((ROOT / "NOTICE").is_file())


if __name__ == "__main__":
    unittest.main()
