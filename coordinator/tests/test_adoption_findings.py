"""Engine-side fixes for what the first real adopter found.

claude-playbooks adapted gentar v0.2.0 into a real repo and hit bugs the
engine's own gate never exercised. Each test here fails against the code as
it was, and names the finding it guards.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gentar.report import RunReport
from gentar.toml_scenario import dropped_credentials, satisfied_group

HERE = Path(__file__).resolve().parent.parent   # coordinator/


def env(**kv):
    return kv.get


class DroppedCredentialsTest(unittest.TestCase):
    """A declared credential that is set but not forwarded must be NAMED.

    Forwarding only the winning group is right; doing it silently is what
    turned claude-playbooks' flat list into "Invalid API key" from inside
    a bench, with nothing pointing back at the scenario."""

    TOKEN, URL, KEY = "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"

    def test_the_adopters_flat_pair_drops_the_url_and_says_so(self):
        flat = [[self.TOKEN], [self.URL]]          # credentials = [TOKEN, URL]
        e = env(ANTHROPIC_AUTH_TOKEN="t", ANTHROPIC_BASE_URL="u")
        self.assertEqual(satisfied_group(flat, e), [self.TOKEN])
        self.assertEqual(dropped_credentials(flat, e), [self.URL])

    def test_grouped_correctly_nothing_is_dropped(self):
        grouped = [[self.TOKEN, self.URL]]         # credentials = [[TOKEN, URL]]
        e = env(ANTHROPIC_AUTH_TOKEN="t", ANTHROPIC_BASE_URL="u")
        self.assertEqual(satisfied_group(grouped, e), [self.TOKEN, self.URL])
        self.assertEqual(dropped_credentials(grouped, e), [])

    def test_a_losing_alternative_that_is_set_is_reported(self):
        # key first-party wins; the router pair is also fully set — dropped,
        # and worth knowing, because the pilot may think the router is used.
        alts = [[self.KEY], [self.TOKEN, self.URL]]
        e = env(ANTHROPIC_API_KEY="k", ANTHROPIC_AUTH_TOKEN="t", ANTHROPIC_BASE_URL="u")
        self.assertEqual(dropped_credentials(alts, e), [self.TOKEN, self.URL])

    def test_unset_names_are_not_reported(self):
        alts = [[self.KEY], [self.TOKEN, self.URL]]
        self.assertEqual(dropped_credentials(alts, env(ANTHROPIC_API_KEY="k")), [])

    def test_nothing_is_dropped_when_nothing_wins(self):
        # the guard refuses that run; a warning on top would be noise
        grouped = [[self.TOKEN, self.URL]]
        self.assertEqual(dropped_credentials(grouped, env(ANTHROPIC_BASE_URL="u")), [])

    def test_the_report_carries_the_warning(self):
        r = RunReport(scenario="s", run_id="r", warnings=["ANTHROPIC_BASE_URL dropped"])
        md = r.markdown()
        self.assertIn("## Warnings", md)
        self.assertIn("ANTHROPIC_BASE_URL dropped", md)


class ParsingNeedsNoPexpectTest(unittest.TestCase):
    """Validating a `key` driver turn must not import pexpect.

    It used to import the key vocabulary from pty_driver, which imports
    pexpect at module top — so on an adopter's host without pexpect, any
    suite with a `key` turn failed to LOAD in dryrun.py. Run in a fresh
    interpreter: earlier tests in this process may already have imported
    pty_driver, which would hide the regression."""

    def test_key_turn_parses_without_pulling_in_pexpect(self):
        toml = (b'[scenario]\nname = "k"\nagent = "shell"\n'
                b'[driver]\ncommand = "true"\n'
                b'[[driver.turns]]\ntype = "key"\nkey = "enter"\n'
                b'[[verify.commands]]\ncommand = "true"\n')
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml)
        try:
            code = ("import sys\n"
                    "from pathlib import Path\n"
                    "from gentar.toml_scenario import TomlScenario\n"
                    f"TomlScenario(Path({f.name!r}))\n"
                    "print('pexpect' in sys.modules, 'gentar.pty_driver' in sys.modules)\n")
            out = subprocess.run([sys.executable, "-c", code], cwd=HERE,
                                 capture_output=True, text=True, check=True).stdout.split()
        finally:
            os.unlink(f.name)
        self.assertEqual(out, ["False", "False"],
                         "parsing a key turn imported pexpect/pty_driver")

    def test_an_unknown_key_is_still_refused(self):
        from gentar.toml_scenario import ScenarioError, TomlScenario
        toml = (b'[scenario]\nname = "k"\nagent = "shell"\n'
                b'[driver]\ncommand = "true"\n'
                b'[[driver.turns]]\ntype = "key"\nkey = "f13"\n'
                b'[[verify.commands]]\ncommand = "true"\n')
        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            f.write(toml)
        try:
            with self.assertRaises(ScenarioError):
                TomlScenario(Path(f.name))
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
