"""Credential-group semantics: entries are ALTERNATIVES, a list entry
is an all-of group — a token without its endpoint must refuse, not
start a misconfigured credentialed bench (PR #26 review). Covers the
guard's whole rule through credentials_satisfied, the schema
validation, and the real agent suites' declared shapes."""

import tempfile
import unittest
from pathlib import Path

from gentar.toml_scenario import (ScenarioError, TomlScenario,
                                  credentials_satisfied)

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def scenario_with_credentials(entries) -> TomlScenario:
    """A minimal valid scenario whose credentials are `entries`
    (None = the key absent entirely)."""
    lines = ["[oracle]", "steps = [\"true\"]"]
    doc = ["[scenario]", "name = \"t\""]
    if entries is not None:
        rendered = ", ".join(
            "[" + ", ".join(repr(n) for n in e) + "]"
            if isinstance(e, list) else repr(e)
            for e in entries)
        doc.append(f"credentials = [{rendered}]")
    path = Path(tempfile.mkdtemp(prefix="gentar-credtest-")) / "t.toml"
    path.write_text("\n".join(doc + lines) + "\n")
    return TomlScenario(path)


class ParseTest(unittest.TestCase):
    def test_str_entry_is_group_of_one(self):
        sc = scenario_with_credentials(["ANTHROPIC_API_KEY"])
        self.assertEqual(sc.credential_groups(), [["ANTHROPIC_API_KEY"]])
        self.assertEqual(sc.credential_names(), ["ANTHROPIC_API_KEY"])

    def test_group_entry_travels_together(self):
        sc = scenario_with_credentials(
            [["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])
        self.assertEqual(sc.credential_groups(),
                         [["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])
        self.assertEqual(sc.credential_names(),
                         ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"])

    def test_mixed_alternatives(self):
        sc = scenario_with_credentials(
            ["ANTHROPIC_API_KEY",
             ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])
        self.assertEqual(sc.credential_groups(),
                         [["ANTHROPIC_API_KEY"],
                          ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])


class ValidationTest(unittest.TestCase):
    def test_nested_group_rejected(self):
        with self.assertRaises(ScenarioError):
            scenario_with_credentials([["A", ["B"]]])

    def test_empty_group_rejected(self):
        with self.assertRaises(ScenarioError):
            scenario_with_credentials([[]])

    def test_non_string_rejected(self):
        with self.assertRaises(ScenarioError):
            scenario_with_credentials([42])

    def test_blank_name_rejected(self):
        with self.assertRaises(ScenarioError):
            scenario_with_credentials(["   "])


class SatisfiedTest(unittest.TestCase):
    def sat(self, groups, env):
        return credentials_satisfied(groups, env.get)

    def test_no_environment_refuses(self):
        self.assertFalse(self.sat([["T", "U"]], {}))

    def test_complete_pair_satisfies(self):
        self.assertTrue(self.sat([["T", "U"]], {"T": "x", "U": "y"}))

    def test_half_pair_refuses(self):
        # The finding: the old any-of guard passed this and started a
        # bench with half a provider.
        self.assertFalse(self.sat([["T", "U"]], {"T": "x"}))

    def test_alternative_single_satisfies(self):
        groups = [["K"], ["T", "U"]]
        self.assertTrue(self.sat(groups, {"K": "x"}))

    def test_alternative_single_missing_pair_still_satisfied(self):
        groups = [["K"], ["T", "U"]]
        self.assertTrue(self.sat(groups, {"K": "x", "T": "y"}))

    def test_pair_only_group_needs_both(self):
        groups = [["K"], ["T", "U"]]
        self.assertFalse(self.sat(groups, {"T": "x"}))

    def test_empty_value_counts_as_missing(self):
        self.assertFalse(self.sat([["T", "U"]], {"T": "x", "U": ""}))


class RealSuitesTest(unittest.TestCase):
    def test_agent_pty_smoke_pins_the_pair(self):
        sc = TomlScenario(SCENARIOS / "agent-pty-smoke.toml")
        self.assertEqual(sc.credential_groups(),
                         [["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])

    def test_agent_smoke_declares_both_provider_shapes(self):
        sc = TomlScenario(SCENARIOS / "agent-smoke.toml")
        self.assertEqual(sc.credential_groups(),
                         [["ANTHROPIC_API_KEY"],
                          ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]])


if __name__ == "__main__":
    unittest.main()
