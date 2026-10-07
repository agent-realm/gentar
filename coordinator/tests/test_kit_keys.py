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
        self.assertIn("trap 'keys_gone; exit 143' INT TERM", td)
        self.assertIn("timeout 180 gentar/run.sh --down &", td)
        self.assertIn("wait $!", td)

    def test_the_teardown_trap_removes_the_keys_when_signalled(self):
        # The step's shell, run for real: a TERM while `run.sh --down` hangs
        # removes both keys at once (well before a SIGKILL would come).
        import os, signal, subprocess, tempfile, time
        td = steps_by_job()["bench"][[s.splitlines()[0] for s in steps_by_job()["bench"]].index("name: teardown")]
        body = "\n".join(l for l in td.splitlines() if not l.startswith(("name:", "if:", "run:", "env:", "GENTAR_", "#")))
        tmp = Path(tempfile.mkdtemp())
        (tmp / "gentar").mkdir()
        (tmp / "gentar" / "run.sh").write_text("#!/bin/sh\nsleep 60\n")
        (tmp / "bin").mkdir()
        # A `timeout` of our own (macOS has none by default): runs the command.
        (tmp / "bin" / "timeout").write_text('#!/bin/sh\nshift\nexec "$@"\n')
        for f in (tmp / "gentar" / "run.sh", tmp / "bin" / "timeout"):
            f.chmod(0o755)
        for k in ("bench_key", "gentar_clone_key"):
            (tmp / k).write_text("x")
        proc = subprocess.Popen(["/bin/bash", "-e", "-c", body], cwd=tmp,
                                env={**os.environ, "RUNNER_TEMP": str(tmp),
                                     "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}"})
        time.sleep(1.0)
        self.assertIsNone(proc.poll(), "the teardown must still be running when the signal comes")
        self.assertTrue((tmp / "bench_key").exists())
        t0 = time.time()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        self.assertLess(time.time() - t0, 5)
        self.assertFalse((tmp / "bench_key").exists())
        self.assertFalse((tmp / "gentar_clone_key").exists())

    def test_jobs_that_write_no_keys_are_untouched(self):
        jobs = steps_by_job()
        self.assertFalse(any(REMOVE in s for s in jobs["plan"]))


if __name__ == "__main__":
    unittest.main()
