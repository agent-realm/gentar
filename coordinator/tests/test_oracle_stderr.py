"""A failed oracle step keeps its stderr tail in the report and the span.

claude-playbooks run 36182588984: cli-completion's build step failed rc=1
and the report showed only the command — the cause went to stderr, which
BenchHost.exec does not return (assertions match on stdout alone).
"""

import unittest
from unittest import mock

from gentar import oracle
from gentar.report import RunReport


class Bench:
    last_stderr = ""

    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    def exec(self, run_id, command, env=None):
        self.last_stderr = self.err
        return self.rc, self.out


class FailedStepStderrTest(unittest.TestCase):

    def run_step(self, bench):
        report = RunReport(scenario="s", run_id="r")
        spans = mock.MagicMock()
        try:
            oracle._step(bench, "sub", "r", "s", spans, 0, "go build ./...", report=report)
        except AssertionError as exc:
            return report, spans, str(exc)
        return report, spans, ""

    def test_the_stderr_tail_reaches_report_span_and_error(self):
        err = "\n".join(f"line {i}" for i in range(100)) + "\nmain.go:3: undefined: Foo"
        report, spans, error = self.run_step(Bench(1, "building...\n", err))
        out = report.steps[0].output
        self.assertIn("main.go:3: undefined: Foo", out)
        self.assertIn("line 99", out)
        self.assertNotIn("line 59\n", out)                 # the last 40 lines only
        detail = spans.step_end.call_args.kwargs["detail"]
        self.assertIn("undefined: Foo", detail)
        self.assertIn("undefined: Foo", error)

    def test_a_passing_step_keeps_stdout_alone(self):
        report, _, _ = self.run_step(Bench(0, "ok\n", "a warning on stderr"))
        self.assertNotIn("warning", report.steps[0].output)


if __name__ == "__main__":
    unittest.main()
