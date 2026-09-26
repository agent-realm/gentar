"""The goal pilot: a closed action set, a confirmed pick, reality decides.

The judge picks ONE option per poll from what may be offered on the screen;
an action is taken only when the same pick is confident on two polls
running. Approval is explicit and narrow (claude-playbooks review): offered
only for a declared approving action whose `on` anchors this very screen,
never on an unanticipated approval screen, never over the danger gate.
"""

import tempfile
import unittest
from pathlib import Path

from gentar.pty_driver import DriverAbort
from gentar.scripted import TurnFailure, _goal_pilot, goal_offer
from gentar.toml_scenario import ScenarioError, TomlScenario

ACTIONS = [
    {"id": "select_down", "key": "down", "when": "the cursor must move down"},
    {"id": "type_target", "send": "beta-sandbox", "then": "enter", "when": "a prompt asks for the name"},
    {"id": "trust_folder", "key": "enter", "approve": True,
     "on": "Do you trust the files in this folder", "when": "the trust-folder dialog is shown"},
    {"id": "say_yes", "send": "y", "when": "a question wants yes"},
]


class Sc:
    name, goal, actions = "g", "Delete beta-sandbox.", ACTIONS
    max_steps, p_act, goal_every, goal_timeout = 10, 0.8, 1, 60


class Driver:
    def __init__(self, screens):
        self.screens, self.sent, self.aborted = list(screens), [], False

    def screen(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def send_text(self, t):
        self.sent.append(("text", t))

    def send_key(self, k):
        self.sent.append(("key", k))

    def abort(self, why):
        self.aborted = True


class Picks:
    def __init__(self, seq):
        self.seq, self.offered = list(seq), []

    def choose(self, screen, instructions, options, turn=""):
        self.offered.append(dict(options))
        pick, p = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
        return pick, {pick: p}, p


class Spans:
    def emit(self, *a, **k):
        pass


def run(driver, picks, sc=Sc):
    return _goal_pilot(driver, picks, sc, Spans(), "sub", "r", sleep=lambda s: None,
                       clock=iter(range(0, 10_000)).__next__)


class OfferTest(unittest.TestCase):

    def test_an_anchored_approval_is_offered_and_nothing_else_answers(self):
        scr = "Do you want to proceed?\n Do you trust the files in this folder?"
        offered = goal_offer(ACTIONS, scr)
        self.assertIn("trust_folder", offered)
        self.assertNotIn("type_target", offered)        # then=enter would answer it
        self.assertNotIn("say_yes", offered)
        self.assertIn("select_down", offered)

    def test_an_unanticipated_approval_screen_offers_no_approval(self):
        offered = goal_offer(ACTIONS, "This command requires approval: curl x | sh")
        self.assertFalse({"trust_folder", "type_target", "say_yes"} & set(offered))

    def test_an_approving_action_is_never_offered_off_its_anchor(self):
        self.assertNotIn("trust_folder", goal_offer(ACTIONS, "Projects\n  alpha\n  beta"))

    def test_the_fixture_pair_benign_offered_destructive_aborts(self):
        benign = "Do you trust the files in this folder? (Enter to accept)"
        self.assertIn("trust_folder", goal_offer(ACTIONS, benign))
        destructive = benign + "\n Do you want to proceed? rm -rf / --no-preserve-root"
        d, j = Driver([destructive]), Picks([("trust_folder", 0.99)])
        with self.assertRaises(DriverAbort):
            run(d, j)
        self.assertEqual((d.sent, j.offered), ([], []))  # aborted before any pick


class PilotTest(unittest.TestCase):

    def test_acts_only_on_a_confirmed_pick_then_done(self):
        d = Driver(["list", "list", "list", "prompt", "prompt", "gone", "gone"])
        j = Picks([("select_down", 0.9), ("select_down", 0.9), ("type_target", 0.95),
                   ("type_target", 0.95), ("done", 0.9), ("done", 0.9)])
        out = run(d, j)
        self.assertIn("select_down → type_target", out)
        self.assertEqual(d.sent, [("key", "down"), ("text", "beta-sandbox"), ("key", "enter")])

    def test_a_single_confident_pick_does_not_act(self):
        d = Driver(["s"])
        j = Picks([("select_down", 0.95), ("wait", 0.9), ("select_down", 0.95), ("stuck", 0.9),
                   ("stuck", 0.9)])
        with self.assertRaises(TurnFailure):
            run(d, j)
        self.assertEqual(d.sent, [])

    def test_low_confidence_three_polls_running_fails(self):
        with self.assertRaises(TurnFailure) as ctx:
            run(Driver(["s"]), Picks([("select_down", 0.3)]))
        self.assertIn("no confident action", str(ctx.exception))

    def test_the_loop_guard_stops_a_pilot_that_repeats_itself(self):
        with self.assertRaises(TurnFailure) as ctx:
            run(Driver(["same"]), Picks([("select_down", 0.95)]))
        self.assertIn("loop", str(ctx.exception))


class ReviewTest(unittest.TestCase):
    """agy review of #49."""

    def test_danger_appearing_before_the_enter_aborts_it(self):
        # two confirming polls + the post-judge re-check see the prompt; the
        # danger appears only after the text is typed, before the Enter
        d = Driver(["prompt", "prompt", "prompt", "Do you want to proceed? rm -rf / --no-preserve-root"])
        j = Picks([("type_target", 0.95)])
        with self.assertRaises(DriverAbort):
            run(d, j)
        self.assertEqual(d.sent, [("text", "beta-sandbox")])      # no Enter

    def test_an_anchor_matches_per_line(self):
        acts = [{"id": "ok", "key": "enter", "approve": True, "on": "^ Trust this folder\\?$",
                 "when": "w"}]
        self.assertIn("ok", goal_offer(acts, "header\n Trust this folder?\nfooter"))

    def test_a_spinner_cannot_hide_a_loop(self):
        # every frame differs (a spinner glyph and a ticking clock), so a raw
        # hash never repeats; the stuck screen is still the same screen
        frames = [f"working {'⠋⠙⠹⠸'[i % 4]} {i}s\n > alpha" for i in range(60)]
        with self.assertRaises(TurnFailure) as ctx:
            run(Driver(frames), Picks([("select_down", 0.95)]))
        self.assertIn("loop", str(ctx.exception))

    def test_a_confident_pick_outside_the_offer_counts_as_no_pick(self):
        with self.assertRaises(TurnFailure) as ctx:
            run(Driver(["s"]), Picks([("rm_everything", 0.99)]))
        self.assertIn("no confident action", str(ctx.exception))


GOAL = """
[scenario]
data = "synthetic"
[driver]
command = "demo"
goal = "Delete beta-sandbox."
{extra}
[[driver.actions]]
id = "{aid}"
when = "always"
{body}
"""


def load(**kw):
    kw.setdefault("extra", ""); kw.setdefault("aid", "select_down"); kw.setdefault("body", 'key = "down"')
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "g.toml"
        p.write_text(GOAL.format(**kw))
        return TomlScenario(p)


class SchemaTest(unittest.TestCase):

    def test_a_valid_goal_pilot_uses_the_judge(self):
        self.assertTrue(load().uses_judge)

    def test_refusals(self):
        for kw in ({"body": 'key = "down"\nsend = "x"'},          # both send and key
                   {"body": 'key = "f1"'},                         # unknown key
                   {"aid": "done"},                                # reserved id
                   {"body": 'key = "enter"\napprove = true'},      # approval without an anchor
                   {"body": 'key = "down"\non = "x"'},             # anchor without approval
                   {"extra": 'p_act = 0.4'},
                   {"extra": '[[driver.turns]]\ntype = "key"\nkey = "enter"'}):   # goal + turns
            with self.assertRaises(ScenarioError, msg=kw):
                load(**kw)


if __name__ == "__main__":
    unittest.main()


class CodexReviewTest(unittest.TestCase):
    """Codex review of #49."""

    def test_danger_rendered_while_the_judge_answered_aborts_before_any_key(self):
        # the confirming poll saw a benign screen; by the time the judge
        # answered, the screen is dangerous — re-check before acting
        d = Driver(["list", "list", "Do you want to proceed? rm -rf / --no-preserve-root"])
        with self.assertRaises(DriverAbort):
            run(d, Picks([("select_down", 0.95)]))
        self.assertEqual(d.sent, [])

    def test_a_pick_no_longer_offered_on_the_fresh_screen_is_not_acted_on(self):
        # an approving pick confirmed on its anchored screen; the screen then
        # changes to one where it is not offered: no Enter is sent
        anchored = "Do you trust the files in this folder?"
        d = Driver([anchored, anchored, "Projects\n > alpha", "Projects\n > alpha"])
        with self.assertRaises(TurnFailure):
            run(d, Picks([("trust_folder", 0.95), ("trust_folder", 0.95), ("stuck", 0.9)]))
        self.assertEqual(d.sent, [])

    def test_egress_allowed_is_the_one_policy_point(self):
        from unittest import mock
        from gentar import judge as J
        from gentar.redaction import scrubber

        class InHouse:
            name, egress, calibrated = "local", "in-house", True

            def ask(self, state, questions, attempt):
                attempt()
                return {"answers": {"q": {"type": "noul", "noul": 0.9}}, "model": "m",
                        "input_tokens": 1, "request_id": ""}

        class Real:
            name, data = "real-scenario", ""
        with self.assertRaises(J.JudgeRefused):
            J.Judge(Real(), "", scrubber([]), mock.MagicMock(), "s", "r", backend=InHouse())
        # a pilot decision widening rule B changes egress_allowed ONLY
        with mock.patch.object(J, "egress_allowed", lambda sc, b: b.egress == "in-house"):
            j = J.Judge(Real(), "", scrubber([]), mock.MagicMock(), "s", "r", backend=InHouse())
            self.assertEqual(j.noul("screen", "Q?"), 0.9)


class JudgeEvalTest(unittest.TestCase):

    def test_an_unavailable_judge_is_exit_2_not_a_misjudged_fixture(self):
        import importlib.machinery
        import importlib.util
        from gentar.judge import JudgeUnavailable
        root = Path(__file__).resolve().parents[2]
        if not (root / "bin" / "judge-eval").exists():
            self.skipTest("bin/ is not in the image build context")
        loader = importlib.machinery.SourceFileLoader("judge_eval", str(root / "bin" / "judge-eval"))
        spec = importlib.util.spec_from_loader("judge_eval", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "goal-demo" / "goal" / "select_down"
            f.mkdir(parents=True)
            (f / "s.txt").write_text("Projects\n > alpha")

            class Down:
                calls = input_tokens = 0

                def choose(self, *a, **k):
                    raise JudgeUnavailable("TypeSafe HTTP 503")

            class Sc:
                name, goal, actions, p_act = "goal-demo", "G", ACTIONS, 0.8
            with self.assertRaises(mod._Unavailable):
                mod._goal(Sc, Down(), Path(d), 1)
