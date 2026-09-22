"""Credential-group semantics: entries are ALTERNATIVES, a list entry
is an all-of group — a token without its endpoint must refuse, not
start a misconfigured credentialed bench (PR #26 review). Covers the
guard's whole rule through credentials_satisfied, the schema
validation, and the real agent suites' declared shapes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar.oracle import cred_env, run_env
from gentar.toml_scenario import (ScenarioError, TomlScenario,
                                  credentials_satisfied, satisfied_group)

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

    def test_satisfied_group_returns_the_winner(self):
        groups = [["K"], ["T", "U"]]
        self.assertEqual(satisfied_group(groups, {"T": "x", "U": "y"}.get),
                         ["T", "U"])

    def test_satisfied_group_prefers_first_declared(self):
        groups = [["K"], ["T", "U"]]
        self.assertEqual(
            satisfied_group(groups, {"K": "a", "T": "x", "U": "y"}.get), ["K"])

    def test_satisfied_group_none_when_incomplete(self):
        self.assertIsNone(satisfied_group([["T", "U"]], {"T": "x"}.get))


class ForwardTest(unittest.TestCase):
    """What actually reaches the bench: the winning group, and only it.

    The guard says yes/no; this says WHICH. A stray half-configured
    alternative must not ride along with the winner — it is how a valid
    key-based run got redirected at another endpoint (review round 3).
    """

    def fwd(self, entries, env):
        sc = scenario_with_credentials(entries)
        with mock.patch.dict(os.environ, env, clear=True):
            return cred_env(sc)

    def test_winning_single_forwards_alone(self):
        self.assertEqual(
            self.fwd(["K", ["T", "U"]], {"K": "x", "U": "http://other"}),
            {"K": "x"})

    def test_winning_group_forwards_whole(self):
        self.assertEqual(
            self.fwd(["K", ["T", "U"]], {"T": "x", "U": "y"}),
            {"T": "x", "U": "y"})

    def test_declaration_order_is_preference(self):
        # Both complete: the first declared alternative wins, and the
        # other's names stay out rather than merging into one env.
        self.assertEqual(
            self.fwd(["K", ["T", "U"]], {"K": "x", "T": "y", "U": "z"}),
            {"K": "x"})

    def test_no_complete_group_forwards_nothing(self):
        # The guard refuses before this point; belt and braces for
        # direct library use — half a provider is worse than none.
        self.assertEqual(self.fwd([["T", "U"]], {"T": "x"}), {})

    def test_pass_env_rides_but_credentials_stay_grouped(self):
        sc = scenario_with_credentials(["K", ["T", "U"]])
        sc.pass_env = ["MODEL_PIN"]
        with mock.patch.dict(os.environ,
                             {"K": "x", "U": "http://other",
                              "MODEL_PIN": "cheap"}, clear=True):
            self.assertEqual(run_env(sc), {"K": "x", "MODEL_PIN": "cheap"})


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
