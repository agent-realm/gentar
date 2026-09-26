"""The docs standard (pilot, 2026-09-26): no release without it.

1) a short README — what, why, how; 2) docs with tutorials and guides;
3) examples, smallest to full, each with its own README.md; 4) an agent
entry for installing and deploying. The kit's plan.py checks the
MECHANICAL half (present, short, links resolve) for adopters who set
[check] docs = true; gentar holds itself to the same check here.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_docs", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_repo(tmp: Path, **overrides) -> Path:
    files = {
        "README.md": "# x\n\nWhat. Why. How: see [the tutorial](docs/tutorials/one.md).\n",
        "AGENTS.md": "# agents\n",
        "docs/tutorials/one.md": "# one\n\nBack to [the README](../../README.md).\n",
        "docs/guides/op.md": "# op\n",
        "examples/01-small/README.md": "# small\n",
    }
    files.update(overrides)
    for rel, text in files.items():
        if text is None:
            continue
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class DocsCheckTest(unittest.TestCase):

    def setUp(self):
        self.plan = load_plan()

    def problems(self, **overrides):
        with tempfile.TemporaryDirectory() as d:
            return self.plan.docs_problems(make_repo(Path(d), **overrides))

    def test_a_complete_repo_is_clean(self):
        self.assertEqual(self.problems(), [])

    def test_each_missing_piece_is_named(self):
        for key, needle in (("README.md", "README.md: missing"),
                            ("AGENTS.md", "AGENTS.md: missing"),
                            ("docs/tutorials/one.md", "docs/tutorials/: missing"),
                            ("docs/guides/op.md", "docs/guides/: missing"),
                            ("examples/01-small/README.md", "examples/01-small/README.md: missing")):
            with self.subTest(key=key):
                # an example directory without its README still exists
                extra = {"examples/01-small/x.toml": "# x\n"} if key.startswith("examples/") else {}
                found = self.problems(**{key: None}, **extra)
                self.assertTrue(any(needle in p for p in found), found)

    def test_a_long_readme_is_named(self):
        long = "# x\n" + "line\n" * (self.plan.README_MAX_LINES + 1)
        self.assertTrue(any("keep it short" in p for p in self.problems(**{"README.md": long})))

    def test_a_broken_relative_link_is_named_urls_and_anchors_are_not(self):
        text = ("# x\n[gone](docs/nope.md) [web](https://example.org) "
                "[anchor](#top) [ok](docs/guides/op.md#part)\n")
        problems = self.problems(**{"README.md": text})
        self.assertEqual([p for p in problems if "broken link" in p],
                         ["README.md: broken link docs/nope.md"])

    def test_edge_cases_from_review(self):
        # a directory named like a page is not a tutorial
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(Path(d), **{"docs/tutorials/one.md": None})
            (repo / "docs" / "tutorials" / "fake.md").mkdir(parents=True)
            self.assertTrue(any("docs/tutorials/: missing" in p
                                for p in self.plan.docs_problems(repo)))
        # links in any example page are checked, repo-root links resolve,
        # hidden directories in examples/ need no README
        found = self.problems(**{"examples/01-small/details.md": "[x](nope.md)\n",
                                 "README.md": "# x\n[root](/docs/guides/op.md)\n",
                                 "examples/.cache/x.txt": "x"})
        self.assertEqual(found, ["examples/01-small/details.md: broken link nope.md"])
        # a link with a title is still a link (Codex)
        titled = self.problems(**{"README.md": '# x\n[g](docs/missing.md "Guide") [ok](docs/guides/op.md \'t\')\n'})
        self.assertEqual([p for p in titled if "broken" in p], ["README.md: broken link docs/missing.md"])

    def test_the_policy_switch_is_a_boolean_and_off_by_default(self):
        self.assertIs(self.plan.SCHEMA["check"]["docs"], False)


@unittest.skipUnless(PLAN.exists() and (ROOT / "docs").exists(),
                     "needs a checkout (docs are not in the image build context)")
class GentarMeetsItsOwnStandardTest(unittest.TestCase):

    def test_gentar_passes_the_docs_check(self):
        self.assertEqual(load_plan().docs_problems(ROOT), [])

    def test_the_template_opts_adopters_in(self):
        text = (ROOT / "subject-template" / "gentar" / "policy.toml").read_text()
        self.assertIn("\ndocs = true", text)


if __name__ == "__main__":
    unittest.main()
