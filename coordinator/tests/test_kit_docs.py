"""The kit README documents every secret and variable the kit workflow reads.

cockpit's v0.9.0 re-pin (Codex) found TYPESAFE_API_KEY, the OTLP pair and
GENTAR_FLOOR read by gentar-arena.yml but missing from the README's
"Secrets/vars the workflow reads" list. An unlisted TYPESAFE_API_KEY hid
that phase 2 skips judged suites without it. This keeps the list complete.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"
README = ROOT / "subject-template" / "gentar" / "README.md"


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class KitDocsTest(unittest.TestCase):

    def listed(self):
        text = README.read_text()
        block = text[text.index("Secrets/vars the workflow reads:"):]
        block = block[:block.index("\n\n", block.index("\n- "))]
        names = set()
        for kind, name in re.findall(r"(secrets|vars)\.([A-Z_{},]+)", block):
            m = re.match(r"(.*)\{([A-Z,]+)\}(.*)", name)
            parts = [m.group(1) + p + m.group(3) for p in m.group(2).split(",")] if m else [name]
            names |= {f"{kind}.{p}" for p in parts}
        return names

    def test_every_name_the_workflow_reads_is_listed(self):
        read = set(re.findall(r"(?:secrets|vars)\.[A-Z_]+", WORKFLOW.read_text()))
        self.assertEqual(sorted(read - self.listed()), [])

    def test_the_judge_skip_is_spelled_out(self):
        text = README.read_text()
        self.assertIn("secrets.TYPESAFE_API_KEY", text)
        self.assertRegex(text, r"skips every judged\s+suite by name")

    def test_fork_prs_with_a_self_hosted_runner_are_said_to_get_no_checks(self):
        self.assertIn("only same-repository PRs", README.read_text())
