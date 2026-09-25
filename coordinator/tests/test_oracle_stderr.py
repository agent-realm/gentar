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

    def test_a_tail_window_that_starts_inside_a_secret_keeps_none_of_it(self):
        # cockpit#31: the failure message keeps the output's LAST 600 chars;
        # when that window starts inside a secret, only its end survives,
        # and the prefix rule never matches an end
        from gentar.redaction import scrubber
        secret = "sk-ant-api03-" + "Q7x9Lm2Pz4Rt8Vw1Ny6Ks3Hd5Fg0Jb"
        err = "token=" + secret + "\n" + "x" * 590
        _, _, error = self.run_step(Bench(1, "", err))
        cut = error[error.index("\n") + 1:]          # the output window
        self.assertNotIn(secret, cut)                 # the window starts inside it
        survivor = cut.split("\n")[0]
        self.assertTrue(secret.endswith(survivor) and len(survivor) >= 8, survivor)
        scrubbed = scrubber([("ANTHROPIC_AUTH_TOKEN", secret)])(error)
        self.assertNotIn(survivor, scrubbed)
        self.assertIn("«redacted:ANTHROPIC_AUTH_TOKEN»", scrubbed)


if __name__ == "__main__":
    unittest.main()
