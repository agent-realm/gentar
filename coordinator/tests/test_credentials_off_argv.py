"""Credential values never ride a command line, an error text, a report or
a span (C1, the 2026-10-19 ground-up review's P0).

They used to: `export K='v'` in the `sbx exec … sh -lc` argv, `env K=v` in
the pty's ssh/`sbx exec -t` command line, both readable by every account on
the bench-host through /proc; a timeout's text was that argv, and it went
into the report (world-readable) and the spans. Now env goes into an
owner-only file in the bench over stdin, in an exec of its own, and is
read, deleted and applied before the command runs.
"""

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.benchhost import (BenchHost, BenchHostError, DaytonaBenchHost,
                              SbxBenchHost, TartBenchHost)
from gentar.config import Config
from gentar.report import RunReport
from gentar.spans import Spans

SECRET = "s3cr3t-VALUE-1"
ENV = {"FAKE_PROVIDER_KEY": SECRET, "SPACEY": "a b'c"}


def cfg(**env):
    base = {"GENTAR_BENCH_HOST": "bench.example.org", "GENTAR_BENCH_USER": "arena",
            "GENTAR_TART_HOST": "mac.example.org", "GENTAR_TART_USER": "tart",
            "GENTAR_DAYTONA_API_KEY": "fake-daytona-key", "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


class Recorder:
    """Stands in for subprocess.run in gentar.benchhost: every argv and
    every stdin, and a successful empty answer."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw.get("input")))
        # The env write says where it staged the file, like a real bench.
        m = re.search(r"\.gentar-env-[0-9a-f]{16}", " ".join(argv)) if kw.get("input") else None
        out = f"/home/user/{m.group(0)}\n" if m else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    def argv_text(self):
        return "\n".join(" ".join(a) for a, _ in self.calls)

    def stdins(self):
        return [i for _, i in self.calls if i]


class Checks:

    def check(self, run, argv_extra=""):
        rec = Recorder()
        with mock.patch("gentar.benchhost.subprocess.run", rec):
            out = run()
        text = rec.argv_text() + "\n" + argv_extra
        self.assertNotIn(SECRET, text)
        self.assertNotIn("a b'c", text)
        self.assertEqual(len(rec.stdins()), 1)
        self.assertIn(f"export FAKE_PROVIDER_KEY={SECRET}\n", rec.stdins()[0])
        self.assertIn("export SPACEY='a b'\"'\"'c'\n", rec.stdins()[0])
        return rec, out


class SbxEnvOffArgvTest(Checks, unittest.TestCase):

    def test_exec_stages_env_over_stdin_then_sources_and_deletes_it(self):
        host = SbxBenchHost(cfg())
        rec, _ = self.check(lambda: host.exec("box1", "echo hi", env=ENV))
        stage, run = rec.calls
        self.assertIn("sbx exec -i box1 sh -c", stage[0][-1])
        self.assertIn('umask 077 && f="${HOME:-/tmp}/.gentar-env-', stage[0][-1])
        self.assertIn('cat > "$f"', stage[0][-1])
        self.assertIn(".gentar-env-", run[0][-1])
        self.assertIn("rm -f", run[0][-1])
        self.assertIsNone(run[1])

    def test_exec_without_env_is_one_call(self):
        host = SbxBenchHost(cfg())
        rec = Recorder()
        with mock.patch("gentar.benchhost.subprocess.run", rec):
            host.exec("box1", "echo hi")
        self.assertEqual(len(rec.calls), 1)
        self.assertNotIn(".gentar-env-", rec.argv_text())

    def test_pty_over_ssh(self):
        host = SbxBenchHost(cfg())
        rec, argv = self.check(lambda: host.pty_spawn_args("box1", 120, 40, ENV, "claude"))
        self.assertEqual(argv[0], "ssh")
        self.assertNotIn(SECRET, " ".join(argv))
        self.assertIn("exec -t box1", argv[-1])

    def test_pty_local(self):
        host = SbxBenchHost(cfg(GENTAR_BENCH_HOST="local"))
        rec, argv = self.check(lambda: host.pty_spawn_args("box1", 120, 40, ENV, "claude"))
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertNotIn(SECRET, " ".join(argv))

    def test_a_name_that_is_not_an_identifier_is_refused(self):
        host = SbxBenchHost(cfg())
        with mock.patch("gentar.benchhost.subprocess.run", Recorder()):
            with self.assertRaises(BenchHostError):
                host.exec("box1", "true", env={"BAD;NAME": "x"})

    def test_a_failed_stage_raises_and_runs_nothing(self):
        host = SbxBenchHost(cfg())
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no space")
        with mock.patch("gentar.benchhost.subprocess.run", run):
            with self.assertRaises(BenchHostError):
                host.exec("box1", "echo hi", env=ENV)
        self.assertEqual(len(calls), 1)


class OtherTiersTest(Checks, unittest.TestCase):

    def tart(self):
        host = TartBenchHost(cfg())
        host._vm_ips["vm1"] = "198.51.100.9"
        return host

    def daytona(self):
        host = DaytonaBenchHost(cfg())
        host._sandboxes["sb1"] = (object(), "tok")
        return host

    def test_tart_exec_and_pty(self):
        host = self.tart()
        self.check(lambda: host.exec("vm1", "echo hi", env=ENV))
        _, argv = self.check(lambda: host.pty_spawn_args("vm1", 120, 40, ENV, "sh"))
        self.assertNotIn(SECRET, " ".join(argv))

    def test_daytona_exec_and_pty(self):
        host = self.daytona()
        self.check(lambda: host.exec("sb1", "echo hi", env=ENV))
        _, argv = self.check(lambda: host.pty_spawn_args("sb1", 120, 40, ENV, "sh"))
        self.assertNotIn(SECRET, " ".join(argv))


class TimeoutTextTest(unittest.TestCase):

    def test_a_timeout_names_the_operation_never_the_argv(self):
        host = SbxBenchHost(cfg())

        def run(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        with mock.patch("gentar.benchhost.subprocess.run", run):
            with self.assertRaises(subprocess.TimeoutExpired) as ctx:
                host._ssh_run(["ssh", "arena@bench"], f"sbx exec box1 sh -lc 'export K={SECRET}; x'",
                              timeout=5)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIn("sbx exec", str(ctx.exception))
        self.assertIsNone(ctx.exception.__context__)


class ReportTest(unittest.TestCase):

    def test_owner_only_and_scrubbed(self):
        spans = Spans.__new__(Spans)
        from gentar.spans import Redactor
        spans.redactor = Redactor(cfg())
        spans.redactor.redact_values([("FAKE_PROVIDER_KEY", SECRET)])
        report = RunReport(scenario="s", run_id="r1", error=f"boom {SECRET}",
                           transcript=f"$ env\nFAKE_PROVIDER_KEY={SECRET}\n")
        report.scrub = spans.redactor.scrub
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "report-r1.md"
            old.write_text("stale")
            os.chmod(old, 0o666)                       # a rerun never keeps a wider mode
            path = report.write(d)
            mode = stat.S_IMODE(path.stat().st_mode)
            text = path.read_text()
        self.assertEqual(mode, 0o600)
        self.assertNotIn(SECRET, text)
        self.assertIn("«redacted:FAKE_PROVIDER_KEY»", text)


class SpanTest(unittest.TestCase):

    def test_local_rows_are_scrubbed(self):
        spans = Spans.__new__(Spans)
        from gentar.spans import Redactor
        spans.cfg = cfg()
        spans.redactor = Redactor(spans.cfg)
        spans.redactor.redact_values([("FAKE_PROVIDER_KEY", SECRET)])
        spans.otlp = mock.MagicMock()
        spans.client = mock.MagicMock()
        spans.emit("sub", "r1", "s", "run.end", "fail", attrs={"why": f"x {SECRET}"},
                   detail=f"boom {SECRET}")
        row = spans.client.insert.call_args[0][1][0]
        self.assertNotIn(SECRET, repr(row))
        exported = spans.otlp.span.call_args[0]
        self.assertNotIn(SECRET, repr(exported))


def write_scenario(d, name, body):
    (Path(d) / f"{name}.toml").write_text(body)


class CoordinatorTest(unittest.TestCase):
    """The run's own error path: whatever text an exception carries, the
    declared value reaches neither the CI log, the report nor a span."""

    def test_an_error_carrying_the_value_is_scrubbed_everywhere(self):
        printed, rows, written = [], [], []

        class Bench:
            push_before_create = True
            def workspace(self, name): return f"/ws/{name}"
            def preflight(self): return []
            def create(self, *a, **k): raise RuntimeError(f"create failed: export K={SECRET}")
            def template_digest(self, tag): return ""
            def exec(self, *a, **k): return 1, ""
            def rm(self, name): pass

        def insert(self, *a):
            rows.append(a)

        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            write_scenario(d, "leaky", '[scenario]\nname = "leaky"\n'
                           'credentials = ["FAKE_PROVIDER_KEY"]\n[oracle]\nsteps = ["true"]\n')
            env = {"GENTAR_SCENARIOS_DIR": d, "GENTAR_BENCH_HOST": "bench.example.org",
                   "GENTAR_BENCH_USER": "arena", "GENTAR_REPORT_DIR": out,
                   "FAKE_PROVIDER_KEY": SECRET}
            with mock.patch.dict(os.environ, env, clear=True):
                c = Config()
                with mock.patch.object(coord, "make_bench", return_value=Bench()), \
                     mock.patch.object(Spans, "_insert", insert), \
                     mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
                    rc = coord._run("leaky", c)
            for p in Path(out).glob("report-*.md"):
                written.append(p.read_text())
        self.assertEqual(rc, 1)
        self.assertTrue(written)
        self.assertNotIn(SECRET, "\n".join(written))
        self.assertNotIn(SECRET, "\n".join(printed))
        # _insert is patched out, so check what the run handed it
        self.assertNotIn(SECRET, repr([r for r in rows if "run.end" in r]))


class OsbGuardTest(unittest.TestCase):

    def test_a_credentialed_driver_scenario_is_refused_on_osb(self):
        self.refused('credentials = ["FAKE_PROVIDER_KEY"]\n')

    def test_a_pass_env_driver_scenario_is_refused_on_osb_too(self):
        # A routed secret can be declared in pass_env (agy on #80).
        self.refused('pass_env = ["FAKE_PROVIDER_KEY"]\n')

    def refused(self, forwards):
        printed = []
        with tempfile.TemporaryDirectory() as d:
            write_scenario(d, "osb-leak", '[scenario]\nname = "osb-leak"\nbench = "osb"\n'
                           + forwards + '[driver]\ncommand = "sh"\n')
            env = {"GENTAR_SCENARIOS_DIR": d, "GENTAR_OSB_SERVER": "http://osb.example.org",
                   "FAKE_PROVIDER_KEY": SECRET, "GENTAR_REPORT_DIR": ""}
            with mock.patch.dict(os.environ, env, clear=True):
                c = Config()
                with mock.patch.object(coord, "make_bench",
                                       side_effect=AssertionError("bench created despite refusal")), \
                     mock.patch.object(coord, "Spans"), \
                     mock.patch("builtins.print", side_effect=printed.append):
                    rc = coord._run("osb-leak", c)
        self.assertEqual(rc, 2)
        self.assertIn("osb guard", "\n".join(map(str, printed)))


RUN_SH = Path(__file__).resolve().parents[2] / "subject-template" / "gentar" / "run.sh"


@unittest.skipUnless(RUN_SH.exists(), "the kit is not in the image build context")
class KitStagedCopyTest(unittest.TestCase):

    def test_the_kits_staged_report_copy_is_owner_only(self):
        text = RUN_SH.read_text()
        self.assertIn('(umask 077; sed "s|^Reproduce:', text)


class ShellHost(BenchHost):
    """_stage_env's real shell behaviour, with this machine's sh as the
    bench: the staged file lands in a temporary HOME."""

    def __init__(self, home):              # no Config: only staging is used
        self.home = home

    def _write_stdin(self, name, remote_sh, content):
        return subprocess.run(["sh", "-c", remote_sh], input=content, text=True, check=True,
                              capture_output=True,
                              env={"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}).stdout


class StagedFileLifecycleTest(unittest.TestCase):
    """The prefix applies every value, leaves no file behind and exports no
    helper variable, even when the env itself moves HOME (Codex on #80: the
    old `. f; rm -f f` expanded the delete's path under the NEW home)."""

    def run_prefixed(self, shell, env, probe):
        home = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        prefix = ShellHost(home)._stage_env("box", env)
        r = subprocess.run([shell, "-c", prefix + probe], capture_output=True, text=True,
                           env={"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        left = [f for f in os.listdir(home) if f.startswith(".gentar-env-")]
        return r, left

    def test_values_arrive_and_the_file_is_gone(self):
        for shell in ("sh", "bash"):
            with self.subTest(shell=shell):
                r, left = self.run_prefixed(shell, ENV, 'printf "%s|%s" "$FAKE_PROVIDER_KEY" "$SPACEY"')
                self.assertEqual((r.returncode, r.stdout), (0, f"{SECRET}|a b'c"), r.stderr)
                self.assertEqual(left, [])

    def test_a_home_override_cannot_strand_the_file(self):
        env = {"HOME": "/elsewhere", **ENV}
        r, left = self.run_prefixed("sh", env, 'printf "%s|%s" "$HOME" "$FAKE_PROVIDER_KEY"')
        self.assertEqual((r.returncode, r.stdout), (0, f"/elsewhere|{SECRET}"), r.stderr)
        self.assertEqual(left, [])

    def test_the_helper_variable_never_reaches_the_program(self):
        r, _ = self.run_prefixed("sh", ENV, 'env')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("__gentar_env", r.stdout)
        self.assertIn(f"FAKE_PROVIDER_KEY={SECRET}", r.stdout)


class StagingPathTest(unittest.TestCase):
    """agy on #80: the command must not re-derive the path from its own
    $HOME; it uses the absolute path the write reported."""

    def test_the_command_uses_the_reported_path(self):
        home = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        prefix = ShellHost(home)._stage_env("box", ENV)
        self.assertNotIn("${HOME", prefix)
        self.assertIn(home + "/.gentar-env-", prefix)
        # The command runs with a DIFFERENT HOME and still finds and removes it.
        r = subprocess.run(["sh", "-c", prefix + 'printf "%s" "$FAKE_PROVIDER_KEY"'],
                           capture_output=True, text=True,
                           env={"HOME": "/nonexistent", "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        self.assertEqual((r.returncode, r.stdout), (0, SECRET), r.stderr)
        self.assertEqual([f for f in os.listdir(home) if f.startswith(".gentar-env-")], [])

    def test_a_bench_that_does_not_report_the_path_is_refused(self):
        class Silent(ShellHost):
            def _write_stdin(self, name, remote_sh, content):
                return "motd noise\n/tmp/.gentar-env-0000000000000000\n"
        with self.assertRaises(BenchHostError):
            Silent("/tmp")._stage_env("box", ENV)


class TimeoutContextTest(unittest.TestCase):

    def test_the_original_timeout_is_not_even_its_context(self):
        host = SbxBenchHost(cfg())
        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 5)
        with mock.patch("gentar.benchhost.subprocess.run", slow):
            with self.assertRaises(subprocess.TimeoutExpired) as cm:
                host._ssh_run(["ssh", "h"], f"sbx exec box sh -lc 'export K={SECRET}'", timeout=5)
        self.assertIsNone(cm.exception.__context__)
        self.assertNotIn(SECRET, str(cm.exception))


class ReportOwnerTest(unittest.TestCase):
    """As root, a report goes to its directory's owner through the open
    descriptor, never by name (agy on #80: a name in a world-writable dir
    can be swapped for a symlink between the write and a chown)."""

    def test_root_hands_the_report_over_by_descriptor(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        real_stat = os.stat
        def stat_(path, *a, **kw):
            st = real_stat(path, *a, **kw)
            if str(path) == d:
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                       4242, 4343, st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
            return st
        with mock.patch("os.geteuid", return_value=0), mock.patch("os.stat", stat_), \
             mock.patch("os.fchown") as fchown, mock.patch("os.chown") as chown:
            RunReport(scenario="s", run_id="r1").write(d)
        self.assertEqual(fchown.call_count, 1)
        self.assertEqual(fchown.call_args.args[1:], (4242, 4343))
        chown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
