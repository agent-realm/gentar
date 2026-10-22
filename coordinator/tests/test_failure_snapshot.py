"""A failed driver turn leaves the session's state in the report.

cockpit's first-run scenario parked after three bench rounds: its TUI never
drew the expected screen, and the report held only the transcript, because
verify does not run after a failed turn. Now a failed turn (or the final
wait timing out, or the danger gate) captures the rendered last screen, the
raw byte tail, the bench's process tree and the scenario's [on_failure]
commands, all scrubbed, before the session is closed.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import scripted
from gentar.report import RunReport
from gentar.toml_scenario import ScenarioError, TomlScenario

SECRET = "sk-SECRETVALUE123"
BASE = '[scenario]\nname = "tui"\n[driver]\ncommand = "cockpit run"\n'
TURN = '[[driver.turns]]\ntype = "expect"\npattern = "Welcome"\ntimeout = 1\n'


def load(text):
    f = Path(tempfile.mkdtemp()) / "tui.toml"
    f.write_text(text)
    return TomlScenario(f)


class FakeDriver:
    def __init__(self, bench, run_id, columns=220, lines=50):
        self.transcript = f"loading {SECRET}\x1b[6n\x1b[?1049h"
        self.closed = False

    def start(self, command, env=None):
        pass

    def drive_until(self, pattern, max_seconds=90):
        return False                                    # the screen never comes

    def screen(self):
        return f"Starting cockpit... token={SECRET}"

    transport = "sbx"

    def wait_done(self, s):
        return True

    def ended(self, settle=10.0):
        return (0, None)            # a clean exit: its status counts since #87

    def close(self):
        self.closed = True


class FakeBench:
    def __init__(self, fail_ps=False):
        self.fail_ps = fail_ps
        self.cmds = []

    def exec(self, run_id, command, timeout=300, env=None):
        self.cmds.append((command, timeout))
        if command.startswith("ps ") and self.fail_ps:
            raise TimeoutError(f"ssh hung after {SECRET}")
        if command.startswith("ps "):
            return 0, f"  PID  PPID STAT TT  ARGS\n  41  1 Ss pts/0 claude --key {SECRET}\n"
        return 3, f"diag output {SECRET}"


def spans():
    s = mock.Mock()
    s.redactor.scrub = lambda t: t.replace(SECRET, "[redacted]")
    return s


class TableTest(unittest.TestCase):

    def test_commands_as_strings_or_tables(self):
        sc = load(BASE + TURN + '[on_failure]\ncommands = ["devbox info", '
                  '{ command = "ls -la ~/.claude", timeout = 20 }]\n')
        self.assertEqual(sc.on_failure, [{"command": "devbox info"},
                                         {"command": "ls -la ~/.claude", "timeout": 20}])
        self.assertEqual(load(BASE + TURN).on_failure, [])

    def test_refusals(self):
        # each refusal says why, so a reverted feature (an unknown table)
        # cannot pass for one (agy on #61)
        entry = r"on_failure\.commands\[0\] must be a command string"
        for bad, why in (('[on_failure]\ncommands = [""]\n', entry),
                         ('[on_failure]\ncommands = [3]\n', entry),
                         ('[on_failure]\ncommands = [{ command = "x", timeout = 0 }]\n', entry),
                         ('[on_failure]\ncommands = [{ command = "x", timeout = true }]\n', entry),
                         ('[on_failure]\ncommands = [{ command = "x", shell = "zsh" }]\n', entry),
                         ('[on_failure]\ncommands = "uptime"\n', r"commands must be a list"),
                         ('[on_failure]\nscript = "x"\n', r"'script'")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ScenarioError, why):
                load(BASE + TURN + bad)
        with self.assertRaisesRegex(ScenarioError, r"needs a \[driver\]"):
            load('[scenario]\nname = "x"\n[oracle]\nsteps = ["true"]\n'
                 '[on_failure]\ncommands = ["ps"]\n')


class SnapshotTest(unittest.TestCase):

    def run_turns(self, bench, text=BASE + TURN):
        sc = load(text)
        report = RunReport(scenario="tui", run_id="r1")
        with mock.patch.object(scripted, "PtyDriver", FakeDriver):
            with self.assertRaises(scripted.TurnFailure):
                scripted.run_turns(sc, bench, "r1", spans(), report=report)
        return report

    def test_a_failed_turn_captures_screen_bytes_processes_and_hooks(self):
        bench = FakeBench()
        r = self.run_turns(bench, BASE + TURN + '[on_failure]\ncommands = ["devbox info"]\n')
        f = r.failure
        self.assertIn("Starting cockpit", f["screen"])
        self.assertIn("\\x1b[6n", f["raw_tail"])             # the escape is visible
        self.assertIn("claude --key", f["processes"])
        self.assertEqual(f["on_failure"][0]["command"], "devbox info")
        self.assertIn("exit 3", f["on_failure"][0]["output"])
        self.assertEqual(bench.cmds[-1], ("devbox info", 60))  # verify's default timeout
        text = r.markdown()
        self.assertIn("## Failure snapshot", text)
        self.assertIn("### on_failure: `devbox info`", text)

    def test_everything_is_scrubbed(self):
        r = self.run_turns(FakeBench(), BASE + TURN + '[on_failure]\ncommands = ["devbox info"]\n')
        self.assertNotIn(SECRET, repr(r.failure))
        # the snapshot section itself; the transcript section after it is the
        # report's existing raw evidence, redacted on publish (bin/redact)
        section = r.markdown().split("## Failure snapshot")[1].split("## Driver transcript")[0]
        self.assertNotIn(SECRET, section)

    def test_a_part_that_cannot_be_read_says_why_and_never_masks_the_failure(self):
        r = self.run_turns(FakeBench(fail_ps=True))
        self.assertIn("could not read: TimeoutError", r.failure["processes"])
        self.assertNotIn(SECRET, r.failure["processes"])        # the error text is scrubbed too
        self.assertIn("Starting cockpit", r.failure["screen"])

    def test_a_snapshot_that_breaks_never_replaces_the_failure(self):
        sc = load(BASE + TURN)
        report = RunReport(scenario="tui", run_id="r1")
        with mock.patch.object(scripted, "PtyDriver", FakeDriver), \
             mock.patch.object(scripted, "failure_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(scripted.TurnFailure):
                scripted.run_turns(sc, FakeBench(), "r1", spans(), report=report)
        self.assertEqual(report.failure, {"error": "snapshot not taken: RuntimeError"})

    def test_a_passing_run_has_no_snapshot(self):
        sc = load(BASE)                                      # no turns: passes
        report = RunReport(scenario="tui", run_id="r1")
        with mock.patch.object(scripted, "PtyDriver", FakeDriver):
            scripted.run_turns(sc, FakeBench(), "r1", spans(), report=report)
        self.assertEqual(report.failure, {})
        self.assertNotIn("Failure snapshot", report.markdown())

    def test_a_program_that_ended_badly_leaves_a_snapshot(self):
        # #87's exit-status failure is a failure like any other turn's
        class Crashed(FakeDriver):
            def ended(self, settle=10.0):
                return (3, None)
        sc = load(BASE)
        report = RunReport(scenario="tui", run_id="r1")
        with mock.patch.object(scripted, "PtyDriver", Crashed):
            with self.assertRaises(scripted.TurnFailure) as cm:
                scripted.run_turns(sc, FakeBench(), "r1", spans(), report=report)
        self.assertIn("exited 3", str(cm.exception))
        self.assertTrue(report.failure)
        self.assertNotIn(SECRET, report.failure["screen"])


class PlainTimeoutTest(unittest.TestCase):
    """GNU timeout's child is a background process group: a TUI under it is
    stopped by SIGTTIN before it draws (cockpit, 2026-10-01)."""

    def test_detection(self):
        from gentar.toml_scenario import plain_timeout as p
        flagged = ["timeout 300 claude", "/usr/bin/timeout 9 x", "cd x && timeout 5 y",
                   "FOO=1 timeout 5 y", "exec timeout 5 y", 'bash -lc "timeout 60 claude"',
                   "timeout -k 5 60 x", "timeout --kill-after 5 60 x",
                   'timeout -s INT 60 bash -lc "cockpit run"',
                   # agy on #61: a prefix by path, a command on a later line
                   "/usr/bin/env timeout 60 claude", "cd /app\ntimeout 60 claude"]
        clean = ["timeout --foreground 300 claude", "timeout -k 5 --foreground 60 x",
                 "timeout --signal=INT --foreground 5 x", "claude --timeout 5", "echo timeout",
                 "echo timeout 5", 'sh -c "cd x && timeout --foreground 5 y"', "cockpit run",
                 "cd /app\ntimeout --foreground 60 claude", "cd /app\necho timeout 5"]
        for c in flagged:
            self.assertTrue(p(c), c)
        for c in clean:
            self.assertFalse(p(c), c)

    def test_warned_only_with_interactive_turns(self):
        self.assertTrue(load(BASE.replace("cockpit run", "timeout 60 cockpit run") + TURN).warnings)
        self.assertFalse(load(BASE.replace("cockpit run", "timeout 60 cockpit run")).warnings)
        self.assertFalse(load(BASE.replace("cockpit run", "timeout --foreground 60 cockpit run")
                              + TURN).warnings)

    def test_the_engines_own_scenarios_are_clean(self):
        scen = Path(__file__).resolve().parents[1] / "scenarios"
        if not scen.exists():
            self.skipTest("scenarios/ is not in this build context")
        for f in sorted(scen.glob("*.toml")):
            self.assertEqual(TomlScenario(f).warnings, [], f.name)


if __name__ == "__main__":
    unittest.main()
