"""The kit's CI jobs do not leave SSH keys behind on a self-hosted runner.

2026-10-08 (cockpit-47, via claude-playbooks-eb): RUNNER_TEMP is not always
emptied when a job is cancelled, and the kit wrote bench_key and
gentar_clone_key there without removing them. Now: keys are written under
umask 077 (no moment where they are readable by others), stale ones are
removed when a job starts, and an always() step removes this job's own at
the end (after teardown, which still needs the bench key).
"""

import re
import unittest
from pathlib import Path

from tests.test_dryrun_fidelity import KIT

WORKFLOW = KIT.parent / ".github" / "workflows" / "gentar-arena.yml"
KEYS = ('"$RUNNER_TEMP/bench_key"', '"$RUNNER_TEMP/gentar_clone_key"')
REMOVE = 'rm -f "$RUNNER_TEMP/bench_key" "$RUNNER_TEMP/gentar_clone_key"'


def steps_by_job():
    """{job: [step text, ...]} from the workflow text (no PyYAML)."""
    jobs, job, steps, in_jobs, cur = {}, None, None, False, None
    for line in WORKFLOW.read_text().splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job, steps, cur = m.group(1), None, None
            jobs[job] = []
            continue
        if job is None:
            continue
        if line.rstrip() == "    steps:":
            steps = jobs[job]
            continue
        if steps is None or line.strip().startswith("#"):
            continue
        if line.startswith("      - "):
            cur = [line.strip().removeprefix("- ")]
            steps.append(cur)
        elif cur is not None and line.startswith("        "):
            cur.append(line.strip())
    return {j: ["\n".join(s) for s in ss] for j, ss in jobs.items()}


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class KeyHygieneTest(unittest.TestCase):

    def test_every_key_write_is_under_umask_077(self):
        writes = [l for l in WORKFLOW.read_text().splitlines()
                  if ">" in l and any(k in l for k in KEYS)]
        self.assertEqual(len(writes), 3, writes)
        for l in writes:
            with self.subTest(line=l.strip()):
                self.assertIn("(umask 077;", l)

    def test_jobs_that_write_keys_start_without_stale_ones(self):
        jobs = steps_by_job()
        for j in ("checks", "bench"):
            with self.subTest(job=j):
                names = [s.splitlines()[0] for s in jobs[j]]
                i = names.index("name: remove stale key files")
                self.assertIn(REMOVE, jobs[j][i])
                writers = [k for k, s in enumerate(jobs[j]) if "umask 077" in s]
                self.assertTrue(writers and i < min(writers), (i, writers))

    def test_jobs_that_write_keys_remove_them_last_and_always(self):
        jobs = steps_by_job()
        for j in ("checks", "bench"):
            with self.subTest(job=j):
                last = jobs[j][-1]
                self.assertIn("if: always()", last)
                self.assertIn(REMOVE, last)
        names = [s.splitlines()[0] for s in jobs["bench"]]
        self.assertLess(names.index("name: teardown"), len(names) - 1)   # teardown first: it needs the key

    def test_a_cancelled_bench_run_cannot_starve_key_removal(self):
        # Codex on #71 (P1): GitHub gives a cancelled run's always() steps
        # five minutes in all; a slow upload or a hung teardown before the
        # final removal could use them up. Now the clone key goes right
        # after the suites, the teardown removes the bench key itself
        # through a trap (with `wait`, so a signal is handled at once) under
        # a timeout, and the upload comes after it.
        steps = steps_by_job()["bench"]
        names = [s.splitlines()[0] for s in steps]
        clone_rm = names.index("name: remove the clone key")
        teardown = names.index("name: teardown")
        upload = names.index("name: upload reports")
        self.assertEqual(names[clone_rm - 1], "name: run suites")
        self.assertTrue(clone_rm < teardown < upload, (clone_rm, teardown, upload))
        self.assertIn("if: always()", steps[clone_rm])
        self.assertIn('rm -f "$RUNNER_TEMP/gentar_clone_key"', steps[clone_rm])
        td = steps[teardown]
        self.assertIn("trap keys_gone EXIT", td)
        self.assertIn("trap 'on_signal 130' INT", td)
        self.assertIn("trap 'on_signal 143' TERM", td)
        self.assertIn("timeout -k 10 180 gentar/run.sh --down & pid=$!", td)
        self.assertIn('wait "$pid"', td)

    def _teardown(self, with_timeout):
        """Run the real teardown step body in a scratch RUNNER_TEMP, with a
        run.sh that records its pid and hangs. Returns (proc, tmp)."""
        import os, subprocess, tempfile, time
        steps = steps_by_job()["bench"]
        td = steps[[s.splitlines()[0] for s in steps].index("name: teardown")]
        body = "\n".join(l for l in td.splitlines()
                         if not l.startswith(("name:", "if:", "run:", "env:", "GENTAR_", "#")))
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gentar").mkdir()
        (tmp / "gentar" / "run.sh").write_text(f'#!/bin/sh\necho $$ > "{tmp}/runsh.pid"\nexec sleep 60\n')
        (tmp / "gentar" / "run.sh").chmod(0o755)
        (tmp / "bin").mkdir()
        if with_timeout:
            # macOS has no `timeout`; this one ignores its options and runs the command.
            (tmp / "bin" / "timeout").write_text('#!/bin/sh\nwhile [ "${1#-}" != "$1" ] || [ "$1" = 10 ]; do shift; done\nshift\nexec "$@"\n')
            (tmp / "bin" / "timeout").chmod(0o755)
            path = f"{tmp / 'bin'}:{os.environ['PATH']}"
        else:
            # no `timeout` anywhere on PATH: only the tools the step needs
            for tool in ("rm", "sleep"):
                (tmp / "bin" / tool).symlink_to(next(Path(d) / tool for d in ("/bin", "/usr/bin") if (Path(d) / tool).exists()))
            path = str(tmp / "bin")
        for k in ("bench_key", "gentar_clone_key"):
            (tmp / k).write_text("x")
        proc = subprocess.Popen(["/bin/bash", "-e", "-c", body], cwd=tmp,
                                env={"RUNNER_TEMP": str(tmp), "PATH": path, "HOME": str(tmp)})
        for _ in range(50):
            if (tmp / "runsh.pid").exists() and (tmp / "runsh.pid").read_text().strip():
                break
            time.sleep(0.1)
        return proc, tmp

    def _alive(self, pid):
        import os
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def test_the_teardown_trap_removes_the_keys_and_stops_the_teardown_when_signalled(self):
        import signal, time
        for with_timeout in (True, False):
            with self.subTest(with_timeout=with_timeout):
                proc, tmp = self._teardown(with_timeout)
                pid = int((tmp / "runsh.pid").read_text())
                self.assertIsNone(proc.poll(), "the teardown must still be running when the signal comes")
                self.assertTrue((tmp / "bench_key").exists())
                t0 = time.time()
                proc.send_signal(signal.SIGTERM)
                rc = proc.wait(timeout=10)
                self.assertLess(time.time() - t0, 5)
                self.assertEqual(rc, 143)
                self.assertFalse((tmp / "bench_key").exists())
                self.assertFalse((tmp / "gentar_clone_key").exists())
                for _ in range(20):
                    if not self._alive(pid):
                        break
                    time.sleep(0.1)
                self.assertFalse(self._alive(pid), "the hung teardown must be stopped too")

    def test_sigint_exits_130(self):
        import signal
        proc, tmp = self._teardown(True)
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(timeout=10), 130)
        self.assertFalse((tmp / "bench_key").exists())

    def test_without_timeout_the_teardown_still_runs(self):
        import subprocess, tempfile
        proc, tmp = self._teardown(False)
        self.assertIsNone(proc.poll())                       # run.sh is running (not skipped)
        proc.terminate(); proc.wait(timeout=10)

    def test_jobs_that_write_no_keys_are_untouched(self):
        jobs = steps_by_job()
        self.assertFalse(any(REMOVE in s for s in jobs["plan"]))


if __name__ == "__main__":
    unittest.main()
