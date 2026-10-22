"""gentar's public CI runs on GitHub-hosted runners only.

D5 (2026-10-08) and the move to a new bench host (2026-10-12; the
operator's acceptance criteria): gentar is public, so no job in any of its workflows
may reach a self-hosted runner -- not by label and not through a variable
that could resolve to one -- and no workflow may reference the bench's
secrets or variables. The bench suites run in the private mirror
agent-realm/gentar-arena, after merge. The bench-free unit tests still run
on every PR and every push to main.
"""

import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
BENCH_NAMES = ("GENTAR_BENCH_KEY", "GENTAR_BENCH_HOST", "GENTAR_BENCH_USER",
               "GENTAR_SUBJECT_TOKEN", "GENTAR_NIGHTLY_SUBJECTS", "GENTAR_OTLP_EXPORT",
               "GENTAR_OTLP_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
               "ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "TYPESAFE_API_KEY")


HOSTED_RUNS_ON = {"runs-on: ubuntu-latest"}


def code_lines(path):
    """The file's lines, comments removed (a comment may name the history)."""
    return [l for l in path.read_text().splitlines() if not l.lstrip().startswith("#")]


@unittest.skipUnless(WORKFLOWS.is_dir(), "the workflows are not in this build context")
class HostedOnlyTest(unittest.TestCase):

    def files(self):
        found = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        self.assertTrue(found)
        return found

    def test_no_job_can_reach_a_self_hosted_runner(self):
        for f in self.files():
            runs_on = [l.strip() for l in code_lines(f) if l.strip().startswith("runs-on:")]
            self.assertTrue(runs_on, f.name)
            for line in runs_on:
                # An explicit allowlist, not a pattern: `ubuntu-private` could be
                # a renamed self-hosted label. Widening it is a deliberate edit.
                with self.subTest(file=f.name, line=line):
                    self.assertIn(line, HOSTED_RUNS_ON)
            text = "\n".join(code_lines(f))
            self.assertNotRegex(text, r"self-hosted|gentar-bench|GENTAR_CI_RUNNER")

    def test_no_workflow_references_a_bench_secret_or_variable(self):
        for f in self.files():
            text = "\n".join(code_lines(f))
            with self.subTest(file=f.name):
                self.assertNotRegex(text, r"\bvars\.")
                for name in BENCH_NAMES:
                    self.assertNotIn(name, text)
                self.assertEqual(re.findall(r"secrets\.[A-Z_]+", text), [])

    def test_the_unit_tests_run_on_every_pr_and_main_push(self):
        text = (WORKFLOWS / "gentar.yml").read_text()
        self.assertIn("\n  pull_request:\n", text)
        self.assertRegex(text, r"push:\n    branches: \[main\]")
        job = text[text.index("  unit-checkout:"):]
        self.assertIn("runs-on: ubuntu-latest", job)
        self.assertIn("python3 -m unittest discover -s tests", job)
        self.assertNotIn("if:", job.split("\n  release-tag:")[0])

    def test_a_release_tag_must_equal_the_version_file(self):
        text = (WORKFLOWS / "gentar.yml").read_text()
        job = text[text.index("  release-tag:"):]
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", job)
        self.assertIn('WANT="v$(cat VERSION)"', job)


if __name__ == "__main__":
    unittest.main()
