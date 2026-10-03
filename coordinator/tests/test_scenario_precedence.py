"""A subject's own suite wins over the engine's baked copy of the same name.

Found 2026-10-03, kommander-playbook's first own-arena run: the engine
listed its baked /app/scenarios first, so every subject suite that shared a
name with one of the engine's (the nine suites gentar used to run for other
repos) was silently replaced by the engine's copy. The subject's fixed
docs-honesty-kommander never ran; the engine's stale one failed instead.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.config import Config
from gentar.scenarios import known_names


def suite(d: Path, name: str, step: str) -> None:
    (d / f"{name}.toml").write_text(
        f'[scenario]\nname = "{name}"\nagent = "shell"\n[oracle]\nsteps = [{step!r}]\n')


def cfg_with(subject_dir: Path, baked_dir: Path) -> Config:
    with mock.patch.dict(os.environ, {"GENTAR_SCENARIOS_DIR": str(subject_dir),
                                      "GENTAR_REPORT_DIR": ""}, clear=True):
        cfg = Config()
    # the baked dir is /app/scenarios in the image; stand in for it here
    cfg.scenarios_dirs = [str(baked_dir) if d == "/app/scenarios" else d
                          for d in cfg.scenarios_dirs]
    return cfg


class PrecedenceTest(unittest.TestCase):

    def setUp(self):
        self.subject = Path(tempfile.mkdtemp())
        self.baked = Path(tempfile.mkdtemp())
        suite(self.baked, "shared", "echo engine-copy")
        suite(self.subject, "shared", "echo subject-copy")
        suite(self.baked, "engine-only", "echo engine-only")
        suite(self.subject, "subject-only", "echo subject-only")
        self.cfg = cfg_with(self.subject, self.baked)

    def test_the_subject_dir_comes_first(self):
        self.assertEqual(self.cfg.scenarios_dirs, [str(self.subject), str(self.baked)])

    def test_a_shared_name_runs_the_subjects_copy_and_says_so(self):
        printed = []
        with mock.patch("builtins.print", side_effect=printed.append):
            _, sc = coord._resolve("shared", self.cfg)
        self.assertEqual(sc.steps, ["echo subject-copy"])
        out = "\n".join(map(str, printed))
        self.assertIn("'shared'", out)
        self.assertIn(f"hides the one in {self.baked}", out)

    def test_unshared_names_resolve_silently_from_either_dir(self):
        for name, step in (("engine-only", "echo engine-only"), ("subject-only", "echo subject-only")):
            printed = []
            with mock.patch("builtins.print", side_effect=printed.append):
                _, sc = coord._resolve(name, self.cfg)
            self.assertEqual(sc.steps, [step])
            self.assertEqual(printed, [])

    def test_known_names_lists_each_once(self):
        names = known_names(self.cfg)
        self.assertEqual(names.count("shared"), 1)
        self.assertIn("engine-only", names)
        self.assertIn("subject-only", names)

    def test_pointing_the_subject_dir_at_the_baked_dir_does_not_duplicate_it(self):
        with mock.patch.dict(os.environ, {"GENTAR_SCENARIOS_DIR": "/app/scenarios",
                                          "GENTAR_REPORT_DIR": ""}, clear=True):
            self.assertEqual(Config().scenarios_dirs, ["/app/scenarios"])


if __name__ == "__main__":
    unittest.main()
