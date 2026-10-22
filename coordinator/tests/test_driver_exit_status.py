"""The driver command's own ending counts; EOF alone is not success.

Ground-up review A3 (2026-10-19): wait_done() returned True on EOF and
nothing read the exit status, so an agent that crashed, was killed by its
`timeout`, or lost its ssh after writing half the work still passed on the
files it left. These run real commands through the engine's own pty path
(PtyDriver over a local `sh -c` transport), no bench, no network.
"""

import signal
import unittest
from unittest import mock

from gentar.pty_driver import exit_problem
from gentar.scripted import TurnFailure, run_turns


class LocalBench:
    """The local sbx transport's shape: the pty is the coordinator's own."""

    def pty_spawn_args(self, sandbox, columns, lines, env, command):
        return ["sh", "-c", command]


class Spans:
    def emit(self, *a, **k):
        pass


class Sc:
    name, goal, uses_judge, actions = "exit-status", "", False, []

    def __init__(self, command, turns=()):
        self.driver_command, self.turns = command, list(turns)


def drive(command, turns=()):
    return run_turns(Sc(command, turns), LocalBench(), "run1", Spans())


class EndingTest(unittest.TestCase):

    def test_a_clean_exit_passes(self):
        self.assertEqual(drive("echo ok; exit 0"), "driver ok: 0 turns")

    def test_a_non_zero_exit_fails_with_its_status(self):
        with self.assertRaises(TurnFailure) as cm:
            drive("echo wrote-half; exit 3")
        self.assertIn("exited 3", str(cm.exception))

    def test_a_timeout_kill_fails_and_says_so(self):
        # timeout(1)'s own status, without depending on GNU timeout here.
        with self.assertRaises(TurnFailure) as cm:
            drive("echo partial; exit 124")
        self.assertIn("timeout(1) killed it", str(cm.exception))

    def test_a_death_by_signal_fails_with_its_name(self):
        with self.assertRaises(TurnFailure) as cm:
            drive("echo crashing; kill -TERM $$")
        self.assertIn("SIGTERM", str(cm.exception))

    def test_a_scenario_that_ends_the_program_with_ctrl_c_still_passes(self):
        # The pty's line discipline turns ^C into SIGINT for the foreground
        # program: the ending the scenario asked for, not a crash.
        turns = [{"type": "key", "after": "ready", "keys": ["ctrl-c"], "delay": 0}]
        self.assertEqual(drive("echo ready; sleep 30", turns), "driver ok: 1 turns")

    def test_ctrl_c_does_not_excuse_any_other_failure(self):
        turns = [{"type": "key", "after": "ready", "keys": ["ctrl-c"], "delay": 0}]
        with self.assertRaises(TurnFailure) as cm:
            drive("trap 'exit 7' INT; echo ready; while :; do sleep 0.1; done", turns)
        self.assertIn("exited 7", str(cm.exception))

    def test_a_goal_whose_program_already_died_fails(self):
        sc = Sc("echo gone; exit 4")
        sc.goal, sc.actions = "Do the thing.", [{"id": "go", "key": "enter"}]

        def goal_pilot(driver, *a, **k):
            driver.wait_done(10)           # the program ends under the pilot
            return "goal done after 0 action(s): none"

        with mock.patch("gentar.scripted._goal_pilot", goal_pilot):
            with self.assertRaises(TurnFailure) as cm:
                run_turns(sc, LocalBench(), "run1", Spans())
        self.assertIn("goal: the driver command exited 4", str(cm.exception))

    def test_a_goal_whose_program_still_runs_passes(self):
        sc = Sc("echo up; sleep 30")
        sc.goal, sc.actions = "Do the thing.", [{"id": "go", "key": "enter"}]
        with mock.patch("gentar.scripted._goal_pilot",
                        lambda *a, **k: "goal done after 0 action(s): none"):
            self.assertEqual(run_turns(sc, LocalBench(), "run1", Spans()),
                             "goal done after 0 action(s): none")


class ExitProblemTest(unittest.TestCase):

    def test_ssh_255_is_named_as_the_transport(self):
        why = exit_problem((255, None), transport="ssh")
        self.assertIn("ssh's own failure code", why)
        self.assertEqual(exit_problem((255, None), transport="sh"), "exited 255")

    def test_a_shell_reported_signal_is_named(self):
        self.assertEqual(exit_problem((137, None)), "exited 137: killed by signal 9 (SIGKILL)")

    def test_sigint_is_excused_only_when_the_scenario_pressed_ctrl_c(self):
        self.assertEqual(exit_problem((None, signal.SIGINT), interrupted=True), "")
        self.assertEqual(exit_problem((130, None), interrupted=True), "")
        self.assertIn("SIGINT", exit_problem((None, signal.SIGINT)))
        self.assertIn("exited 130", exit_problem((130, None)))

    def test_no_exit_after_eof_is_not_a_pass(self):
        self.assertIn("had not exited", exit_problem(None))
        self.assertIn("no exit status", exit_problem((None, None)))


if __name__ == "__main__":
    unittest.main()
