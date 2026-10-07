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

    def test_jobs_that_write_no_keys_are_untouched(self):
        jobs = steps_by_job()
        self.assertFalse(any(REMOVE in s for s in jobs["plan"]))


if __name__ == "__main__":
    unittest.main()
