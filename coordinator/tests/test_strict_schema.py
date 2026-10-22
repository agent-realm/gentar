"""The scenario schema is closed: an unknown table or key is refused.

Ignoring one turned a typo into a weaker test that still passed (review
2026-10-19, A2): `contain = "x"` in [[verify.files]] became a bare
existence check, and a [[verify.command]] table (singular) was dropped,
leaving "0/0 assertions passed".
"""

import tempfile
import unittest
from pathlib import Path

from gentar.toml_scenario import ScenarioError, TomlScenario

ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path(__file__).resolve().parents[1]
ORACLE = '[scenario]\n[oracle]\nsteps = ["true"]\n'


def load(text: str) -> TomlScenario:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.toml"
        p.write_text(text)
        return TomlScenario(p)


class ClosedSchemaTest(unittest.TestCase):

    def refused(self, text: str, *needles: str) -> None:
        with self.assertRaises(ScenarioError) as cm:
            load(text)
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_a_misspelled_assertion_key_is_refused_with_a_suggestion(self):
        self.refused(ORACLE + '[[verify.files]]\npath = "/etc/hosts"\ncontain = "x"\n',
                     "verify.files[0]", "'contain'", "did you mean 'contains'?")
        self.refused(ORACLE + '[[verify.commands]]\ncommand = "true"\ncontans = "x"\n',
                     "verify.commands[0]", "did you mean 'contains'?")

    def test_a_singular_verify_command_table_is_refused(self):
        self.refused(ORACLE + '[[verify.command]]\ncommand = "false"\n',
                     "[verify]", "'command'", "did you mean 'commands'?")

    def test_an_unknown_top_level_table_is_refused(self):
        self.refused(ORACLE + '[[verfy.files]]\npath = "/x"\n',
                     "unknown table(s) 'verfy'", "did you mean 'verify'?")
        self.refused('name = "loose"\n' + ORACLE, "unknown table(s) 'name'")

    def test_an_unknown_key_in_a_fixed_table_is_refused(self):
        self.refused('[scenario]\nsubjct = "s"\n[oracle]\nsteps = ["true"]\n',
                     "[scenario]", "did you mean 'subject'?")
        self.refused('[scenario]\n[oracle]\nstep = ["true"]\n', "[oracle]", "'steps'")
        self.refused(ORACLE + '[budget]\ntoken = 5\n', "[budget]", "'tokens'")

    def test_a_turn_key_its_type_never_reads_is_refused(self):
        drv = '[scenario]\n[driver]\ncommand = "d"\n[[driver.turns]]\n'
        self.refused(drv + 'type = "expect"\npattern = "x"\nsend = "y"\n',
                     "driver.turns[0] (expect)", "'send'")
        self.refused(drv + 'type = "answer"\nprompt = "x"\nsned = "y"\n',
                     "did you mean 'send'?")

    def test_single_brackets_on_an_array_of_tables_are_refused(self):
        self.refused(ORACLE + '[verify.files]\npath = "/x"\n',
                     "verify.files must be an array of tables", "[[verify.files]]")

    def test_every_documented_key_is_still_accepted(self):
        s = load('[scenario]\nname = "n"\nsubject = "s"\nagent = "shell"\n'
                 'template = "t"\nbench = "sbx"\nbench_only = "why"\ndata = "synthetic"\n'
                 'credentials = ["K", ["T", "U"]]\npass_env = ["P"]\n'
                 '[oracle]\nsteps = ["true"]\n'
                 '[driver]\ncommand = "d"\n'
                 '[[driver.turns]]\ntype = "answer"\nprompt = "p"\nsend = "s"\ntimeout = 5\n'
                 '[[driver.turns]]\ntype = "expect"\npattern = "x"\ntimeout = 5\n'
                 '[[driver.turns]]\ntype = "pick"\nlabel = "l"\ntries = 3\noptional = true\n'
                 '[[driver.turns]]\ntype = "key"\nkeys = ["enter"]\nafter = "a"\ndelay = 0.1\n'
                 'timeout = 5\noptional = true\n'
                 '[[driver.turns]]\ntype = "abort"\ntimeout = 5\n'
                 '[[verify.files]]\npath = "/x"\ncontains = "y"\n'
                 '[[verify.commands]]\ncommand = "true"\ncontains = ""\n'
                 '[[verify.judge]]\nquestion = "Q?"\n'
                 '[judge]\nmax_calls = 1\nmax_input_tokens = 1\nlines = 10\n'
                 '[budget]\ntokens = 1\nsimulate_spend = 1\n')
        self.assertEqual((len(s.turns), len(s.files), len(s.commands)), (5, 1, 1))

    def test_every_shipped_scenario_parses(self):
        # the engine's own suites sit beside tests/ (coordinator/ in the
        # repo, the image build's context); the examples and the kit only in
        # a full checkout
        shipped = [*ENGINE.glob("scenarios/*.toml"),
                   *ROOT.glob("examples/*/gentar/scenarios/*.toml"),
                   *ROOT.glob("subject-template/gentar/scenarios/*.toml")]
        self.assertGreater(len(shipped), 20 if (ROOT / "examples").is_dir() else 5)
        for f in shipped:
            with self.subTest(f=f.name):
                TomlScenario(f)


if __name__ == "__main__":
    unittest.main()
