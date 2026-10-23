"""The kit reads a suite's TOML with a TOML parser, as the engine does (A7).

run.sh used to read scenarios with awk and grep, and its reading diverged
from the engine's (ground-up review 2026-10-19, A7):
- GB6: `judged()` was a grep for `goal`/`judge` keys, so a deterministic step
  that prints `goal=1` made the suite judged, and a sweep skipped it;
- GB7: the [scenario] reader toggled its multi-line-string state inside
  comments, so a comment holding triple quotes hid the table: no subject,
  no credentials;
- SB10: `credentials = []` read as a credential never set, so a sweep
  skipped a suite that needs none;
- GB2: a `[scenario] name` other than the file name broke the sweep and
  let `run.sh <name>` pass the pull request guard under a name with no file.

Now `plan.py scenarios` reads every suite with tomllib, run.sh asks it, and
a test below holds its reading to the engine's TomlScenario.
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gentar.toml_scenario import TomlScenario

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
PLAN = KIT / "plan.py"


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_toml", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = '[scenario]\nsubject = "x"\n'
GOAL_ACTIONS = '[[driver.actions]]\nid = "a"\nkey = "down"\nwhen = "w"\n'
JUDGE = '{ question = "q?", p_min = 0.8, hold = 2 }'

# Every way the old grep looked for, written as a whole scenario the engine
# loads, with what the engine says about it.
SPELLINGS = {
    "goal": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\ngoal = "G"\n'
             + GOAL_ACTIONS),
    "quoted-goal": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\n"goal" = "G"\n'
                    + GOAL_ACTIONS),
    "dotted-goal": (True, 'driver.goal = "G"\ndriver.command = "d"\n' + BASE
                    + 'data = "synthetic"\n' + GOAL_ACTIONS),
    "judged-turn": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\n'
                    f'[[driver.turns]]\ntype = "expect"\njudge = {JUDGE}\n'),
    "quoted-judge": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\n'
                     f'[[driver.turns]]\ntype = "expect"\n"judge" = {JUDGE}\n'),
    "soft-check": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\n'
                   '[[driver.turns]]\ntype = "expect"\npattern = "x"\n'
                   '[[verify.judge]]\nquestion = "Q?"\n'),
    "quoted-soft": (True, BASE + 'data = "synthetic"\n[driver]\ncommand = "d"\n'
                    '[[driver.turns]]\ntype = "expect"\npattern = "x"\n'
                    '[["verify"."judge"]]\nquestion = "Q?"\n'),
    # GB6: text that mentions the words is not a judged turn
    "prints-goal": (False, BASE + '[oracle]\nsteps = ["printf goal=1", "echo judge = 2"]\n'),
    "commented": (False, BASE + '# goal = "G"\n# [[verify.judge]]\n[oracle]\nsteps = ["true"]\n'),
    "commands": (False, BASE + '[oracle]\nsteps = ["true"]\n'
                 '[[verify.commands]]\ncommand = "true"\n'),
}


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class ScenariosReaderTest(unittest.TestCase):

    def setUp(self):
        self.plan = load_plan()
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def facts(self, **files):
        for stem, text in files.items():
            (self.d / f"{stem}.toml").write_text(text)
        return {x["stem"]: x for x in self.plan.scenario_facts(self.d)}

    def test_a_step_printing_goal_is_not_judged(self):                     # GB6
        f = self.facts(plain=BASE + '[oracle]\nsteps = ["printf goal=1"]\n')
        self.assertFalse(f["plain"]["judged"])

    def test_a_comment_with_triple_quotes_hides_nothing(self):             # GB7
        f = self.facts(s='# a note about """ and \'\'\' quoting\n'
                         '[scenario]\nsubject = "x"\ncredentials = ["KEY_A", ["TOK", "URL"]]\n'
                         'pass_env = ["MODEL"]\n[oracle]\nsteps = ["true"]\n')
        self.assertEqual(f["s"]["subject"], "x")
        self.assertEqual(f["s"]["groups"], [["KEY_A"], ["TOK", "URL"]])
        self.assertEqual(f["s"]["forwarded"], ["KEY_A", "TOK", "URL", "MODEL"])

    def test_an_empty_credentials_list_needs_nothing(self):                # SB10
        f = self.facts(s=BASE + 'credentials = []\n[oracle]\nsteps = ["true"]\n')
        self.assertEqual(f["s"]["groups"], [])

    def test_a_name_other_than_the_file_name_is_refused(self):             # GB2
        with self.assertRaisesRegex(self.plan.Refuse, "differs from the file name.*bar.toml"):
            self.facts(foo='[scenario]\nname = "bar"\nsubject = "x"\n')
        (self.d / "foo.toml").unlink()
        self.assertIn("same", self.facts(same='[scenario]\nname = "same"\nsubject = "x"\n'))

    def test_judged_suites_refuses_the_mismatch_too(self):
        (self.d / "foo.toml").write_text('[scenario]\nname = "bar"\n')
        self.plan.SCENARIOS = self.d
        with self.assertRaisesRegex(self.plan.Refuse, "differs from the file name"):
            self.plan.judged_suites()

    def test_refusals(self):
        cases = {
            "not valid TOML": "[scenario\n",
            "bad subject name": '[scenario]\nsubject = "a b"\n',
            r"credentials\[0\] must be an env var name": '[scenario]\ncredentials = ["1BAD"]\n',
            r"credentials\[1\] must be": '[scenario]\ncredentials = ["A", []]\n',
            r"pass_env\[0\] must be an env var name": '[scenario]\npass_env = [3]\n',
            "are lists": '[scenario]\ncredentials = "A"\n',
            r"\[scenario\] must be a table": 'scenario = 1\n',
        }
        for why, text in cases.items():
            with self.subTest(why=why):
                for f in self.d.glob("*.toml"):
                    f.unlink()
                with self.assertRaisesRegex(self.plan.Refuse, why):
                    self.facts(s=text)

    def test_a_scalar_driver_or_verify_is_refused_not_a_crash(self):          # agy D4
        for table in ("driver", "verify"):
            with self.subTest(table=table):
                for f in self.d.glob("*.toml"):
                    f.unlink()
                with self.assertRaisesRegex(self.plan.Refuse, f"{table} must be a table"):
                    self.facts(s=f'{table} = "cmd"\n' + BASE)
        for table in ("driver", "verify"):         # both at once, for judged_suites
            (self.d / f"{table}.toml").write_text(f'{table} = "cmd"\n' + BASE)
        self.plan.SCENARIOS = self.d
        self.assertEqual(self.plan.judged_suites(strict=False), {})

    def test_utf8_whatever_the_locale(self):                                 # agy D1
        repo = self.d / "repo"
        shutil.copytree(KIT, repo / "gentar")
        sc = repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        (sc / "s.toml").write_text('# René — a note\n' + BASE + '[oracle]\nsteps = ["echo é"]\n',
                                   encoding="utf-8")
        env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        r = subprocess.run(["python3", str(repo / "gentar" / "plan.py"), "scenarios"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "s\tx\t0\t\t\n")

    def test_a_file_name_outside_the_suite_charset_is_refused(self):
        with self.assertRaisesRegex(self.plan.Refuse, "suite file name"):
            self.facts(**{"a b": BASE})

    def test_the_command_prints_one_tab_separated_line_per_suite(self):
        repo = self.d / "repo"
        shutil.copytree(KIT, repo / "gentar")
        sc = repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        (sc / "a.toml").write_text(BASE + 'credentials = ["K", ["T", "U"]]\npass_env = ["M"]\n')
        (sc / "b.toml").write_text(SPELLINGS["judged-turn"][1])
        r = subprocess.run(["python3", str(repo / "gentar" / "plan.py"), "scenarios"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "a\tx\t0\tK;T U\tK T U M\nb\tx\t1\t\t\n")


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class MatchesTheEngineTest(unittest.TestCase):
    """plan.py's reading is the engine's, on every scenario we have."""

    def setUp(self):
        self.plan = load_plan()

    def same(self, directory):
        checked = 0
        for x in self.plan.scenario_facts(directory):
            sc = TomlScenario(directory / f"{x['stem']}.toml")
            where = f"{directory.name}/{x['stem']}"
            self.assertEqual(x["subject"], sc.subject or "", where)
            self.assertEqual(x["judged"], sc.uses_judge, where)
            self.assertEqual(x["groups"], sc.credential_groups(), where)
            want = list(dict.fromkeys([n for g in sc.credential_groups() for n in g]
                                      + sc.pass_env))
            self.assertEqual(x["forwarded"], want, where)
            checked += 1
        return checked

    def test_every_scenario_in_the_repo(self):
        dirs = [ROOT / "coordinator" / "scenarios", KIT / "scenarios"]
        dirs += sorted(p for p in (ROOT / "examples").glob("*/gentar/scenarios") if p.is_dir())
        n = sum(self.same(d) for d in dirs if d.is_dir())
        self.assertGreater(n, 20)

    def test_both_refuse_a_string_where_a_list_belongs(self):              # agy D2
        from gentar.toml_scenario import ScenarioError
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for field in ("credentials", "pass_env"):
                with self.subTest(field=field):
                    f = d / "s.toml"
                    f.write_text(BASE + f'{field} = "KEY_A"\n[oracle]\nsteps = ["true"]\n')
                    with self.assertRaisesRegex(ScenarioError, f"{field} must be a list"):
                        TomlScenario(f)
                    with self.assertRaisesRegex(self.plan.Refuse, "are lists"):
                        self.plan.scenario_facts(d)

    def test_every_judged_spelling(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for stem, (want, text) in SPELLINGS.items():
                (d / f"{stem}.toml").write_text(text)
            self.same(d)
            got = {x["stem"]: x["judged"] for x in self.plan.scenario_facts(d)}
            self.assertEqual(got, {k: v[0] for k, v in SPELLINGS.items()})


@unittest.skipUnless((KIT / "run.sh").exists() and shutil.which("bash"),
                     "the kit is not in the image build context")
class RunShReadsWithTheParserTest(unittest.TestCase):
    """End to end: what a sweep runs and skips, and what it refuses."""

    def sweep(self, *args, **suites):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        sc = repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        shutil.rmtree(repo / "gentar" / "reports", ignore_errors=True)
        (repo / "gentar" / "policy.toml").unlink(missing_ok=True)
        for stem, text in suites.items():
            (sc / f"{stem}.toml").write_text(text)
        e = dict(os.environ, GENTAR_REPO_URL=str(tmp / "no-engine"))
        for k in ("TYPESAFE_API_KEY", "A7_TEST_KEY", "GITHUB_EVENT_NAME", "CI",
                  "GITHUB_ACTIONS", "GENTAR_SUBJECT"):
            e.pop(k, None)
        r = subprocess.run(["/bin/bash", "gentar/run.sh", *(args or ("--sweep",))], cwd=repo,
                           env=e, capture_output=True, text=True, timeout=120)
        listed = repo / "gentar" / "reports" / "sweep-skipped.txt"
        return r, (listed.read_text() if listed.exists() else None)

    def test_gb6_sb10_gb7_in_one_sweep(self):
        r, listed = self.sweep(
            prints=BASE + '[oracle]\nsteps = ["printf goal=1"]\n',
            empty=BASE + 'credentials = []\n[oracle]\nsteps = ["true"]\n',
            hidden='# about """ quoting\n' + BASE
                   + 'credentials = ["A7_TEST_KEY"]\n[oracle]\nsteps = ["true"]\n')
        self.assertIsNotNone(listed, r.stderr)
        self.assertEqual(listed, "hidden\tno credential group of it is fully set\n")
        self.assertIn("sweep: empty prints", r.stderr)

    def test_numeric_looking_stems_keep_their_own_facts(self):
        # Codex on #96: awk's `==` compared 01 and 1 as numbers
        r, listed = self.sweep(**{"01": BASE + '[oracle]\nsteps = ["true"]\n',
                                  "1": SPELLINGS["judged-turn"][1]})
        self.assertIsNotNone(listed, r.stderr)
        self.assertEqual(listed, "1\tit has judged turns and TYPESAFE_API_KEY is not set\n")
        self.assertIn("sweep: 01\n", r.stderr + "\n")

    def test_a_name_other_than_the_file_name_refuses_the_run(self):
        r, _ = self.sweep(foo='[scenario]\nname = "bar"\nsubject = "x"\n[oracle]\nsteps = ["true"]\n')
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("differs from the file name", r.stderr)
        self.assertIn("the scenarios do not read", r.stderr)

    def test_stage_engine_is_not_refused_for_a_broken_suite(self):
        # --stage-engine (and --check, which calls it) stages no subject: a
        # broken suite is --check's to report, through lint and the dry-run
        r, _ = self.sweep("--stage-engine", broken="[scenario\n")
        self.assertNotIn("the scenarios do not read", r.stderr)
        self.assertNotIn("not valid TOML", r.stderr)      # said once, by --check

    def test_lint_lists_a_name_mismatch_with_the_other_problems(self):
        plan = load_plan()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "named.toml").write_text('[scenario]\nname = "other"\nsubject = "x"\n')
            (d / "broken.toml").write_text("[scenario\n")
            plan.SCENARIOS = d
            problems = plan.lint(None, str(d / "no-engine"))
        self.assertTrue(any("broken.toml: not valid TOML" in p for p in problems), problems)
        self.assertTrue(any("named.toml: [scenario] name = 'other' differs" in p
                            for p in problems), problems)

    def test_lint_lists_what_run_sh_would_refuse(self):                    # agy D2
        plan = load_plan()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.toml").write_text(BASE + 'credentials = "KEY_A"\n')
            (d / "b.toml").write_text(BASE + 'pass_env = [3]\n')
            (d / "c.toml").write_text('[scenario]\nsubject = "a b"\n')
            (d / "d.toml").write_text('driver = "cmd"\n' + BASE)
            plan.SCENARIOS = d
            problems = "\n".join(plan.lint(None, str(d / "no-engine")))
        for want in ("a.toml: scenario.credentials and scenario.pass_env are lists",
                     "b.toml: scenario.pass_env[0] must be an env var name",
                     "c.toml: bad subject name", "d.toml: driver must be a table"):
            self.assertIn(want, problems)


@unittest.skipUnless((ROOT / "bin" / "arena").exists() and shutil.which("bash"),
                     "bin/arena is not in the image build context")
class BinArenaReadsCommentsTest(unittest.TestCase):
    """gentar's own runner keeps its awk reader (no python on the host), with
    GB7 fixed: a comment no longer flips the multi-line-string state, and an
    inline comment declares nothing."""

    def env_names(self, text):
        src = (ROOT / "bin" / "arena").read_text()
        i = src.index("scenario_table() {")
        fns = src[i:src.index("\n# Sets FORWARD", i)]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.toml"
            f.write_text(text)
            r = subprocess.run(["/bin/bash", "-c", fns + f'\nextract_env_names "{f}"'],
                               capture_output=True, text=True)
        return r.stdout.split()

    def test_a_comment_with_triple_quotes_hides_nothing(self):
        self.assertEqual(self.env_names('# about """ quoting\n[scenario]\nsubject = "x"\n'
                                        'credentials = ["A"]\n'), ["A"])

    def test_an_inline_comment_with_triple_quotes_hides_nothing(self):       # agy D3
        self.assertEqual(self.env_names('timeout = 30 # wait for """ prompt\n[scenario]\n'
                                        'subject = "x"\ncredentials = ["A"]\n[oracle]\n'
                                        'steps = ["echo # not a comment"]\n'), ["A"])

    def test_an_inline_comment_declares_nothing(self):
        self.assertEqual(self.env_names('[scenario]\npass_env = ["B"]  # was "C"\n'), ["B"])


if __name__ == "__main__":
    unittest.main()
