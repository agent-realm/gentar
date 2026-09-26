"""examples/ — the ladder from a one-step oracle to a full subject.

The docs standard (pilot, 2026-09-26) asks for examples from the smallest
feature to a full usage, each with its own README.md. This holds them to
it mechanically: every example documented, every scenario loads with the
engine's own parser, judged ones declare synthetic data and carry the
fixtures the kit's lint requires, names never collide, and no README links
to a file that is not there.
"""

import re
import unittest
from pathlib import Path

from gentar.toml_scenario import TomlScenario

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
MIN_FIXTURES = 3
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


@unittest.skipUnless(EXAMPLES.exists(), "examples/ is not in the image build context")
class ExamplesTest(unittest.TestCase):

    def dirs(self):
        return sorted(p for p in EXAMPLES.iterdir() if p.is_dir())

    def scenarios(self):
        return sorted(EXAMPLES.glob("*/gentar/scenarios/*.toml"))

    def test_every_example_has_its_own_readme(self):
        self.assertTrue(self.dirs())
        for d in self.dirs():
            self.assertTrue((d / "README.md").is_file(), d.name)
        self.assertTrue((EXAMPLES / "README.md").is_file())

    def test_every_scenario_loads_and_names_are_unique(self):
        names = {}
        for f in self.scenarios():
            sc = TomlScenario(f)
            self.assertNotIn(sc.name, names, f"{f} and {names.get(sc.name)}")
            names[sc.name] = f
            self.assertEqual(sc.subject, "example", f)
        self.assertGreaterEqual(len(names), 8)

    def test_judged_examples_are_synthetic_and_measured(self):
        judged = 0
        for f in self.scenarios():
            sc = TomlScenario(f)
            if not sc.uses_judge:
                continue
            judged += 1
            self.assertEqual(sc.data, "synthetic", f)
            fixtures = f.parent.parent / "judge-fixtures" / sc.name
            for i, t in enumerate(sc.turns):
                if "judge" in t:
                    for label in ("yes", "no"):
                        n = len(list((fixtures / str(i) / label).glob("*.txt")))
                        self.assertGreaterEqual(n, MIN_FIXTURES, f"{f.name} turn {i} {label}")
            if sc.goal:
                picks = {d.name: len(list(d.glob("*.txt")))
                         for d in (fixtures / "goal").glob("*") if d.is_dir()}
                self.assertIn("done", picks, f.name)
                self.assertGreaterEqual(len(picks), 2, f.name)
                self.assertGreaterEqual(sum(picks.values()), MIN_FIXTURES, f.name)
                offered = {a["id"] for a in sc.actions} | {"wait", "done", "stuck"}
                self.assertLessEqual(set(picks), offered, f"{f.name}: fixture for an unknown action")
        self.assertGreaterEqual(judged, 3)

    def test_every_relative_link_resolves(self):
        for readme in EXAMPLES.rglob("README.md"):
            for target in LINK.findall(readme.read_text()):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path = (readme.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(path.exists(), f"{readme.relative_to(ROOT)} -> {target}")


if __name__ == "__main__":
    unittest.main()
