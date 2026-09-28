"""The driller session loop (gentar/drill.py), with a fake pty and a fake model.

The model proposes; the coordinator decides what reaches the bench. Every
test here is about a byte that must or must not be sent.
"""

import unittest
from types import SimpleNamespace as NS

from gentar import drill as d

SECRET = "sk-SECRETVALUE123"


def step(kind, text=None, enter=None, key=None, why="w"):
    return NS(kind=NS(value=kind), text=text, enter=enter, key=key, why=why)


class FakeDriver:
    def __init__(self, screens):
        self.screens = list(screens)
        self.sent = []          # ("text", s) / ("key", k)
        self.aborted = None

    def screen(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def send_text(self, s):
        self.sent.append(("text", s))

    def send_key(self, k):
        self.sent.append(("key", k))

    def abort(self, why):
        self.aborted = why


class FakeModel:
    def __init__(self, steps, notes="notes", fail_at=None):
        self.steps = list(steps)
        self._notes = notes
        self.fail_at = fail_at
        self.calls = 0
        self.input_tokens = 0
        self.seen_screens = []

    def next(self, charter, brief, screen, history):
        self.calls += 1
        self.input_tokens += 100
        self.seen_screens.append(screen)
        if self.fail_at is not None and self.calls == self.fail_at:
            raise TimeoutError("model down")
        return self.steps.pop(0) if self.steps else step("DONE")

    def notes(self, charter, brief, history, screen):
        self.calls += 1
        return self._notes


def run(driver, model, budget=None, scrub=lambda s: s, clock=None):
    return d.drill(driver, model, "charter", "brief", scrub, budget or d.DrillBudget(every=0),
                   sleep=lambda s: None, clock=clock or (lambda: 0.0))


class DrillTest(unittest.TestCase):

    def test_a_normal_session(self):
        drv = FakeDriver(["$ "])
        m = FakeModel([step("TYPE", "ls -la ~", enter=True), step("WAIT"),
                       step("KEY", key="Down"), step("DONE")], notes="found nothing")
        r = run(drv, m)
        self.assertEqual(drv.sent, [("text", "ls -la ~"), ("key", "enter"), ("key", "down")])
        self.assertEqual((r.ended, r.steps, r.notes), ("done", 2, "found nothing"))
        self.assertEqual(r.boundary, [])

    def test_a_dangerous_command_is_never_typed(self):
        drv = FakeDriver(["$ "])
        r = run(drv, FakeModel([step("TYPE", "sudo rm -rf / --no-preserve-root", enter=True)]))
        self.assertEqual(drv.sent, [])
        self.assertEqual(r.ended, "danger: typed text")
        self.assertEqual(len(r.boundary), 1)
        self.assertEqual(r.notes, "notes")          # still asked for notes

    def test_danger_on_the_screen_aborts_before_asking(self):
        drv = FakeDriver(["Do you want to proceed? rm -rf / "])
        m = FakeModel([step("TYPE", "y", enter=True)])
        r = run(drv, m)
        self.assertEqual((drv.sent, r.ended), ([], "danger: screen"))
        self.assertIsNotNone(drv.aborted)
        self.assertEqual(m.seen_screens, [])

    def test_danger_appearing_while_the_model_thinks_stops_the_keypress(self):
        drv = FakeDriver(["$ ", "$ mkfs.ext4 /dev/sda"])
        r = run(drv, FakeModel([step("KEY", key="enter")]))
        self.assertEqual((drv.sent, r.ended), ([], "danger: screen"))

    def test_danger_before_enter_sends_the_text_but_not_enter(self):
        drv = FakeDriver(["$ ", "$ ", "$ shutdown -h now"])
        r = run(drv, FakeModel([step("TYPE", "x", enter=True)]))
        self.assertEqual(drv.sent, [("text", "x")])
        self.assertEqual(r.ended, "danger: screen")

    def test_keys_outside_the_vocabulary_are_refused(self):
        drv = FakeDriver(["$ "])
        m = FakeModel([step("KEY", key="ctrl-z"), step("KEY", key="f5"), step("KEY", key=None),
                       step("DONE")])
        r = run(drv, m)
        self.assertEqual(drv.sent, [])
        self.assertEqual(sum("REFUSED" in h for h in r.history), 3)
        self.assertEqual(r.ended, "done")

    def test_control_characters_and_newlines_are_refused(self):
        drv = FakeDriver(["$ "])
        bad = ["\x1b[2J", "a\nrm x", "\x03", "\x7f", "\u009b31m", ""]
        r = run(drv, FakeModel([step("TYPE", t) for t in bad] + [step("DONE")]))
        self.assertEqual(drv.sent, [])
        self.assertEqual(sum("REFUSED" in h for h in r.history), len(bad))
        ok = run(FakeDriver(["$ "]), FakeModel([step("TYPE", "ls\t"), step("DONE")]))
        self.assertEqual(ok.steps, 1)                 # a tab is fine (completion)

    def test_unknown_step_kinds_are_refused(self):
        drv = FakeDriver(["$ "])
        r = run(drv, FakeModel([step("EXEC", "id"), step("DONE")]))
        self.assertEqual(drv.sent, [])
        self.assertIn("unknown step kind", r.history[0])

    def test_budgets_end_the_session_not_the_run(self):
        # steps
        m = FakeModel([step("KEY", key="up")] * 10)
        r = run(FakeDriver(["$ "]), m, budget=d.DrillBudget(steps=3, every=0))
        self.assertEqual((r.steps, r.ended), (3, "budget: 3 steps"))
        self.assertEqual(r.notes, "notes")
        # model calls / tokens
        r = run(FakeDriver(["$ "]), FakeModel([step("WAIT")] * 10),
                budget=d.DrillBudget(calls=4, every=0))
        self.assertTrue(r.ended.startswith("budget: model"))
        r = run(FakeDriver(["$ "]), FakeModel([step("WAIT")] * 10),
                budget=d.DrillBudget(input_tokens=250, every=0))
        self.assertTrue(r.ended.startswith("budget: model"))
        # wall clock
        t = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0])
        r = run(FakeDriver(["$ "]), FakeModel([step("WAIT")] * 10),
                budget=d.DrillBudget(seconds=10, every=0), clock=lambda: next(t))
        self.assertTrue(r.ended.startswith("budget:") and "wall clock" in r.ended)

    def test_a_model_failure_ends_the_session_and_notes_are_still_tried(self):
        r = run(FakeDriver(["$ "]), FakeModel([step("WAIT")], fail_at=2))
        self.assertEqual(r.ended, "model: TimeoutError")
        self.assertEqual(r.notes, "notes")

    def test_the_model_only_ever_sees_scrubbed_text(self):
        scrub = lambda s: s.replace(SECRET, "[redacted]")
        drv = FakeDriver([f"token={SECRET}\n$ "])
        m = FakeModel([step("TYPE", f"echo {SECRET}", enter=True, why=f"saw {SECRET}"),
                       step("DONE")], notes=f"the token {SECRET} is shown")
        r = run(drv, m, scrub=scrub)
        self.assertTrue(all(SECRET not in s for s in m.seen_screens))
        self.assertTrue(all(SECRET not in h for h in r.history))
        self.assertNotIn(SECRET, r.notes)
        # what is TYPED is the model's text, unscrubbed: the pty needs the
        # real characters; only what we record and send out is scrubbed
        self.assertEqual(drv.sent[0], ("text", f"echo {SECRET}"))


try:
    import baml_py  # noqa: F401
    HAVE_BAML = True
except ModuleNotFoundError:
    HAVE_BAML = False


@unittest.skipUnless(HAVE_BAML, "baml-py not installed (it is in the image)")
class BamlModelTest(unittest.TestCase):

    def test_boundary_key_in_the_model_env_refuses(self):
        with self.assertRaises(RuntimeError):
            d.BamlModel({"BOUNDARY_API_KEY": ""})

    def test_steps_parse_from_messy_output(self):
        from gentar.baml_client import b
        s = b.parse.DrillerStep('Sure. {"kind": "type", "text": "cat ~/.tool/config", '
                                '"enter": true, "why": "check perms",}')
        self.assertEqual((s.kind.value, s.text, s.enter), ("TYPE", "cat ~/.tool/config", True))
        self.assertIsNone(d.step_problem(s))


if __name__ == "__main__":
    unittest.main()
