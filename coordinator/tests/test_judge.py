"""Semantic turns: what may leave the arena, and when a judged turn passes.

The pilot's rule (2026-09-26): a judge sees only the current screen,
scrubbed, and only for a scenario declared synthetic — refused before any
bench exists otherwise. The audit keeps a hash and a length, never the
text. A judged expect needs the same confident yes on consecutive polls
(TypeSafe's Choice answers moved on identical requests in the probe), never
presses anything, and the deterministic danger gate still fires first.
"""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.config import Config
from gentar.judge import MODEL, Judge, JudgeRefused, JudgeUnavailable, prepare_screen
from gentar.pty_driver import DriverAbort
from gentar.redaction import scrubber
from gentar.scripted import TurnFailure, _judged
from gentar.toml_scenario import ScenarioError, TomlScenario

SECRET = "sk-ant-api03-Q7x9Lm2Pz4Rt8Vw1Ny6Ks3Hd5Fg0Jb"


class Scn:
    def __init__(self, data="synthetic", name="demo"):
        self.data, self.name = data, name


def fake_post(answers, record):
    def post(body):
        record.append(json.loads(body))
        return ({"model": MODEL, "answers": answers,
                 "usage": {"input_tokens": 600, "output_tokens": 5}},
                {"x-typesafe-request-id": "req-1"})
    return post


def judge(**kw):
    record = []
    spans = mock.MagicMock()
    j = Judge(kw.pop("scenario", Scn()), kw.pop("key", "k-test"),
              kw.pop("scrub", scrubber([("ANTHROPIC_AUTH_TOKEN", SECRET)])),
              spans, "sub", "run1",
              post=kw.pop("post", None) or fake_post({"q": {"type": "noul", "noul": 0.97}}, record),
              sleep=lambda s: None, **kw)
    return j, record, spans


class EgressTest(unittest.TestCase):

    def test_only_a_synthetic_scenario_may_send_a_screen(self):
        for data in ("", "real", "Synthetic "):
            with self.assertRaises(JudgeRefused, msg=data):
                judge(scenario=Scn(data=data))

    def test_no_key_no_judge(self):
        with self.assertRaises(JudgeRefused):
            judge(key="")

    def test_only_the_scrubbed_screen_leaves(self):
        j, record, spans = judge()
        screen = "\x1b[31m╭────╮\x1b[0m\nDelete beta? token " + SECRET + "\n╰────╯"
        self.assertEqual(j.noul(screen, "Does `screen` ask to delete beta?"), 0.97)
        (body,) = record
        self.assertEqual(set(body), {"state", "model", "questions"})
        self.assertEqual(set(body["state"]), {"screen"})
        sent = body["state"]["screen"]
        self.assertNotIn(SECRET[:12], sent)
        self.assertNotIn("\x1b", sent)
        self.assertNotIn("╭", sent)
        self.assertEqual(body["model"], MODEL)

    def test_the_audit_span_keeps_a_hash_never_the_text(self):
        j, record, spans = judge()
        j.noul("Delete beta-sandbox? type its name", "Q?", turn="3")
        attrs = spans.emit.call_args.kwargs["attrs"]
        blob = json.dumps(attrs)
        self.assertEqual(len(attrs["judge.sent_sha256"]), 64)
        self.assertEqual(attrs["judge.model"], MODEL)
        self.assertEqual(attrs["judge.q.p_yes"], "0.97")
        self.assertNotIn("beta-sandbox", blob)
        self.assertNotIn("detail", spans.emit.call_args.kwargs)

    def test_the_hash_is_of_exactly_the_bytes_sent(self):
        # root review: scrub after prepare, before hashing AND sending — the
        # audit's sha256 must identify the very screen that left
        import hashlib
        j, record, spans = judge()
        j.noul("\x1b[1mDelete beta?\x1b[0m token " + SECRET + "\n\n\n", "Q?")
        sent = record[0]["state"]["screen"]
        attrs = spans.emit.call_args.kwargs["attrs"]
        self.assertEqual(attrs["judge.sent_sha256"], hashlib.sha256(sent.encode()).hexdigest())
        self.assertEqual(int(attrs["judge.sent_chars"]), len(sent))
        self.assertNotIn(SECRET[:12], sent)

    def test_retries_a_rate_limit_then_answers(self):
        calls = []

        def post(body):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 429, "slow down", {"retry-after": "0"}, io.BytesIO())
            return ({"model": MODEL, "answers": {"q": {"type": "noul", "noul": 0.9}},
                     "usage": {"input_tokens": 1}}, {})
        j, _, _ = judge(post=post)
        self.assertEqual(j.noul("s", "Q?"), 0.9)
        self.assertEqual(len(calls), 2)
        self.assertEqual(j.calls, 2)            # every attempt counts (Codex)

    def test_retries_cannot_exceed_the_call_cap(self):
        calls = []

        def post(body):
            calls.append(1)
            raise urllib.error.HTTPError("u", 503, "busy", {"retry-after": "0"}, io.BytesIO())
        j, _, _ = judge(post=post, max_calls=2)
        with self.assertRaises(JudgeUnavailable):
            j.noul("s", "Q?")
        self.assertEqual(len(calls), 2)          # not 3: the cap stops the retries

    def test_the_egress_ceiling_is_forty_rows_whatever_is_passed(self):
        j, record, _ = judge(lines=1000)
        self.assertEqual(j.lines, 40)
        j.noul("\n".join(f"row {i}" for i in range(60)), "Q?")
        self.assertEqual(record[0]["state"]["screen"].count("\n"), 39)

    def test_an_auth_error_is_not_retried(self):
        def post(body):
            raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO())
        j, _, _ = judge(post=post)
        with self.assertRaises(JudgeUnavailable):
            j.noul("s", "Q?")

    def test_the_budget_caps_calls(self):
        j, record, _ = judge(max_calls=2)
        j.noul("s", "Q?"); j.noul("s", "Q?")
        with self.assertRaises(JudgeUnavailable):
            j.noul("s", "Q?")
        self.assertEqual(len(record), 2)

    def test_prepare_skips_the_blank_rows_below_the_content(self):
        # live semantic-demo run: the rendered screen is 49 rows with the
        # content on top and 41 blank rows below; "the last 40 rows" sent
        # the judge an EMPTY screen, and it rightly said no for 60s
        screen = "demo-cli\n\n You are about to remove beta-sandbox for good.\n" + "\n" * 41
        out = prepare_screen(screen, lines=40)
        self.assertIn("remove beta-sandbox", out)
        self.assertTrue(out.startswith("demo-cli"))

    def test_an_empty_screen_is_a_no_without_a_call(self):
        j, record, spans = judge()
        self.assertEqual(j.noul("\n\n\x1b[2J  \n", "Q?"), 0.0)
        self.assertEqual(record, [])
        self.assertEqual(j.calls, 0)

    def test_prepare_keeps_the_last_rows_only(self):
        screen = "\n".join(f"row {i}" for i in range(100))
        self.assertEqual(prepare_screen(screen, lines=3), "row 97\nrow 98\nrow 99")


class Driver:
    def __init__(self, screens):
        self.screens, self.sent, self.aborted = list(screens), [], False

    def screen(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def send_key(self, k):
        self.sent.append(k)

    def send_line(self, t):
        self.sent.append(t)

    def abort(self, why):
        self.aborted = True


class Seq:
    def __init__(self, ps):
        self.ps, self.asked = list(ps), 0

    def noul(self, screen, question, **kw):
        self.asked += 1
        return self.ps.pop(0) if len(self.ps) > 1 else self.ps[0]


def turn(**j):
    return {"type": "expect", "timeout": 30,
            "judge": {"question": "Does `screen` ask to delete beta?", "every": 3, **j}}


class JudgedExpectTest(unittest.TestCase):

    def test_passes_only_on_a_held_yes(self):
        d, s = Driver(["screen"]), Seq([0.95, 0.5, 0.95, 0.96])
        out = _judged(d, s, turn(p_min=0.9, hold=2), 0, sleep=lambda x: None)
        self.assertIn("held 2", out)
        self.assertEqual(s.asked, 4)                   # a single yes did not count
        self.assertEqual(d.sent, [])                   # never pressed anything

    def test_a_timeout_names_the_band(self):
        with self.assertRaises(TurnFailure) as no:
            _judged(Driver(["s"]), Seq([0.05]), turn(), 0, sleep=lambda x: None)
        self.assertIn("a clear no", str(no.exception))
        with self.assertRaises(TurnFailure) as mid:
            _judged(Driver(["s"]), Seq([0.6]), turn(), 0, sleep=lambda x: None)
        self.assertIn("undecided", str(mid.exception))

    def test_the_danger_gate_fires_before_the_judge_is_asked(self):
        d = Driver(["Do you want to proceed?\n  rm -rf / --no-preserve-root"])
        s = Seq([0.99])
        with self.assertRaises(DriverAbort):
            _judged(d, s, turn(), 0, sleep=lambda x: None)
        self.assertTrue(d.aborted)
        self.assertEqual(s.asked, 0)

    def test_an_unavailable_judge_fails_the_turn_by_name(self):
        class Down:
            def noul(self, *a, **k):
                raise JudgeUnavailable("TypeSafe HTTP 503")
        with self.assertRaises(TurnFailure) as ctx:
            _judged(Driver(["s"]), Down(), turn(), 0, sleep=lambda x: None)
        self.assertIn("judge unavailable", str(ctx.exception))


SCENARIO = """
[scenario]
name = "{name}"
{data}

[driver]
command = "demo"
[[driver.turns]]
type = "expect"
judge = {{ question = "Does `screen` ask to delete beta?" }}
"""


def write(tmp, name, data=""):
    p = Path(tmp) / f"{name}.toml"
    p.write_text(SCENARIO.format(name=name, data=data))
    return p


class SchemaTest(unittest.TestCase):

    def test_expect_needs_exactly_one_of_pattern_or_judge(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.toml"
            p.write_text('[scenario]\n[driver]\ncommand = "c"\n[[driver.turns]]\ntype = "expect"\n'
                         'pattern = "x"\njudge = { question = "Q?" }\n')
            with self.assertRaises(ScenarioError):
                TomlScenario(p)

    def test_bad_thresholds_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.toml"
            p.write_text('[scenario]\n[driver]\ncommand = "c"\n[[driver.turns]]\ntype = "expect"\n'
                         'judge = { question = "Q?", p_min = 0.4 }\n')
            with self.assertRaises(ScenarioError):
                TomlScenario(p)

    def test_the_judge_key_can_never_be_forwarded_to_a_bench(self):
        with tempfile.TemporaryDirectory() as d:
            for field in ('credentials = ["TYPESAFE_API_KEY"]', 'pass_env = ["TYPESAFE_API_KEY"]'):
                p = Path(d) / "x.toml"
                p.write_text(f'[scenario]\n{field}\n[oracle]\nsteps = ["true"]\n')
                with self.assertRaises(ScenarioError, msg=field):
                    TomlScenario(p)

    def test_a_single_yes_can_never_pass_a_turn(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.toml"
            p.write_text('[scenario]\n[driver]\ncommand = "c"\n[[driver.turns]]\ntype = "expect"\n'
                         'judge = { question = "Q?", hold = 1 }\n')
            with self.assertRaises(ScenarioError):
                TomlScenario(p)

    def test_judge_lines_beyond_the_egress_ceiling_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for lines in (0, 41, 1000):
                p = Path(d) / "x.toml"
                p.write_text(f'[scenario]\n[judge]\nlines = {lines}\n[oracle]\nsteps = ["true"]\n')
                with self.assertRaises(ScenarioError, msg=lines):
                    TomlScenario(p)

    def test_uses_judge(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(TomlScenario(write(d, "a")).uses_judge)


def refuse_run(tmp, scenario, **env):
    printed = []
    with mock.patch.dict(os.environ, {"GENTAR_SCENARIOS_DIR": tmp, **env}, clear=True):
        cfg = Config()
        with mock.patch.object(coord, "make_bench",
                               side_effect=AssertionError("bench created despite refusal")), \
             mock.patch.object(coord, "Spans"), \
             mock.patch.object(coord, "_write_report"), \
             mock.patch("builtins.print", side_effect=printed.append):
            rc = coord.run(scenario, cfg)
    return rc, "\n".join(map(str, printed))


class JudgeGuardTest(unittest.TestCase):

    def test_a_non_synthetic_judged_scenario_is_refused_before_any_bench(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "judged-real")
            rc, out = refuse_run(d, "judged-real", TYPESAFE_API_KEY="k")
        self.assertEqual(rc, 2)
        self.assertIn("synthetic", out)

    def test_a_judged_scenario_without_the_key_is_refused_before_any_bench(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "judged-nokey", data='data = "synthetic"')
            rc, out = refuse_run(d, "judged-nokey")
        self.assertEqual(rc, 2)
        self.assertIn("TYPESAFE_API_KEY", out)


class KeyIsScrubbedTest(unittest.TestCase):

    def test_the_judge_key_value_is_scrubbed_from_everything_exported(self):
        from gentar.spans import Redactor
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "ts-key-0123456789abcdef"}, clear=True):
            r = Redactor(Config())
        self.assertNotIn("0123456789", r.scrub("auth ts-key-0123456789abcdef"))


if __name__ == "__main__":
    unittest.main()
