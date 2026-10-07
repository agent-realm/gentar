"""The kit's CI jobs keep their temp files in the runner's per-job temp dir.

2026-10-07: a self-hosted runner LXC (ci-runner-arf) went offline when its
tmpfs /tmp filled with 7.4 GB of leaked test dirs. On a self-hosted runner
/tmp is shared and never cleaned; RUNNER_TEMP is emptied after every job.
The kit's dry-run keeps a failing suite's scratch home "for inspection", and
suites' own mktemp steps leak, so the jobs that can run self-hosted point
TMPDIR at RUNNER_TEMP first.
"""

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_dryrun_fidelity import KIT, _ScratchAdoption

WORKFLOW = KIT.parent / ".github" / "workflows" / "gentar-arena.yml"


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class WorkflowTest(unittest.TestCase):

    @staticmethod
    def jobs():
        """{job: (runs-on text, first step's lines)}, read from the YAML
        text: no PyYAML (it is not a coordinator dependency), so the test
        runs on any checkout (Codex on #68)."""
        out, job, runs_on, first, dashes, in_jobs = {}, None, "", None, 0, False
        def close():
            if job:
                out[job] = (runs_on, first or [])
        for line in WORKFLOW.read_text().splitlines():
            if line.rstrip() == "jobs:":
                in_jobs = True
                continue
            if not in_jobs or line.strip().startswith("#"):
                continue
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                close()
                job, runs_on, first, dashes = m.group(1), "", None, 0
                continue
            if line.startswith("    runs-on:"):
                runs_on = line.split(":", 1)[1].strip()
            elif line.rstrip() == "    steps:":
                first = []
            elif first is not None:
                if line.startswith("      - "):
                    dashes += 1
                if dashes == 1 and line.startswith("      "):
                    first.append(line.strip().lstrip("- ").strip())
        close()
        return out

    def test_every_job_that_can_run_self_hosted_sets_tmpdir_first(self):
        jobs = self.jobs()
        can_self_host = sorted(j for j, (r, _) in jobs.items()
                               if "self-hosted" in r or "GENTAR_CI_RUNNER" in r)
        self.assertEqual(can_self_host, ["bench", "checks", "plan"])
        for j in can_self_host:
            with self.subTest(job=j):
                first = jobs[j][1]
                self.assertIn('run: echo "TMPDIR=$RUNNER_TEMP" >> "$GITHUB_ENV"', first, first)

    def test_the_arena_lock_and_bench_root_stay_fixed_paths(self):
        run = (KIT / "run.sh").read_text()
        self.assertIn('LOCK_ROOT="${GENTAR_LOCK_DIR:-/tmp}/gentar-locks"', run)
        self.assertIn("GENTAR_BENCH_WORKSPACE_ROOT:-/tmp/gentar-workspaces", run)


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class DryrunHonoursTmpdirTest(_ScratchAdoption):

    def test_a_failing_suites_kept_home_lands_under_tmpdir(self):
        self.suite("broken", ["false"])
        job_temp = Path(tempfile.mkdtemp())
        r = self.dryrun(TMPDIR=str(job_temp))
        self.assertEqual(r.returncode, 1, r.stdout)
        kept = [l for l in r.stdout.splitlines() if "home kept for inspection" in l]
        self.assertTrue(kept, r.stdout)
        self.assertIn(str(job_temp), kept[0])
        self.assertTrue(any(p.name.startswith("dryrun-home-") for p in job_temp.iterdir()))


if __name__ == "__main__":
    unittest.main()
