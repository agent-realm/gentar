"""A phase 2 that skipped a suite is not a proof of the commit (v0.10.0).

The ground-up review (2026-10-19, A1): a sweep skips every suite whose key
is not set and exits 0 when the suites it ran passed. In the arena mirror
that green became an `arena/phase2` success and a `phase2-green-<sha>`
marker, after which the schedule never swept the commit again. Now run.sh
writes the list of skipped suites, and the mirror's bench job fails on a
non-empty (or missing) list before it marks anything green, so the status
names them instead.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
MIRROR_WF = ROOT / "subject-template" / "mirror" / "arena" / ".github" / "workflows" / "arena.yml"
GUARD = "      - name: phase 2 ran every suite"


def guard_script():
    """The guard step's `run: |` body, dedented (no PyYAML)."""
    lines = MIRROR_WF.read_text().splitlines()
    i = lines.index(GUARD)
    j = next(k for k in range(i, len(lines)) if lines[k].strip() == "run: |")
    body = []
    for line in lines[j + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


@unittest.skipUnless((KIT / "run.sh").exists(), "the kit is not in the image build context")
class SweepWritesItsSkipsTest(unittest.TestCase):

    def sweep(self, **env):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        shutil.rmtree(repo / "gentar" / "scenarios")
        (repo / "gentar" / "scenarios").mkdir()
        shutil.rmtree(repo / "gentar" / "reports", ignore_errors=True)
        (repo / "gentar" / "policy.toml").unlink(missing_ok=True)
        base = '[scenario]\nsubject = "x"\n'
        (repo / "gentar" / "scenarios" / "plain.toml").write_text(
            base + '[oracle]\nsteps = ["true"]\n')
        (repo / "gentar" / "scenarios" / "needs-key.toml").write_text(
            base + 'credentials = ["GUARD_TEST_KEY"]\n[oracle]\nsteps = ["true"]\n')
        (repo / "gentar" / "scenarios" / "judged.toml").write_text(
            base + 'data = "synthetic"\n[driver]\ncommand = "bash"\n'
            '[[driver.turns]]\ntype = "expect"\njudge = { question = "q?", p_min = 0.8, hold = 2 }\n')
        e = dict(os.environ, GENTAR_REPO_URL=str(tmp / "no-engine"))
        for k in ("TYPESAFE_API_KEY", "GUARD_TEST_KEY", "GITHUB_EVENT_NAME", "CI", "GITHUB_ACTIONS"):
            e.pop(k, None)
        e.update(env)
        r = subprocess.run(["/bin/bash", "gentar/run.sh", "--sweep"], cwd=repo, env=e,
                           capture_output=True, text=True)
        listed = repo / "gentar" / "reports" / "sweep-skipped.txt"
        return r, (listed.read_text() if listed.exists() else None)

    def test_every_skip_is_listed_with_its_reason(self):
        r, listed = self.sweep()
        self.assertIsNotNone(listed, r.stderr)
        rows = dict(line.split("\t", 1) for line in listed.splitlines())
        self.assertEqual(set(rows), {"needs-key", "judged"})
        self.assertEqual(rows["needs-key"], "no credential group of it is fully set")
        self.assertEqual(rows["judged"], "it has judged turns and TYPESAFE_API_KEY is not set")
        self.assertIn("sweep: plain", r.stderr)
        self.assertIn("skipping needs-key — no credential group of it is fully set", r.stderr)

    def test_a_sweep_that_skips_nothing_writes_an_empty_list(self):
        r, listed = self.sweep(GUARD_TEST_KEY="set-for-the-test",
                               TYPESAFE_API_KEY="set-for-the-test")
        self.assertEqual(listed, "", r.stderr)


@unittest.skipUnless(MIRROR_WF.exists(), "the kit is not in the image build context")
class MirrorGuardTest(unittest.TestCase):

    def guard(self, listed):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "gentar" / "reports").mkdir(parents=True)
        if listed is not None:
            (tmp / "gentar" / "reports" / "sweep-skipped.txt").write_text(listed)
        out = tmp / "github_output"
        out.write_text("")
        r = subprocess.run(["/bin/bash", "-e", "-c", guard_script()], cwd=tmp,
                           env=dict(os.environ, GITHUB_OUTPUT=str(out)),
                           capture_output=True, text=True)
        return r, out.read_text()

    def test_a_skipped_suite_fails_the_job_and_names_it(self):
        r, out = self.guard("needs-key\tno credential group of it is fully set\n"
                            "judged\tit has judged turns and TYPESAFE_API_KEY is not set\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(out, "skipped=needs-key judged\n")
        self.assertIn("::error title=phase 2 not proven::skipped: needs-key judged", r.stdout)

    def test_no_list_is_not_a_proof_either(self):
        r, out = self.guard(None)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(out, "")

    def test_an_empty_list_passes(self):
        r, out = self.guard("")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out, "")

    def test_a_hostile_name_cannot_write_a_workflow_command(self):
        r, out = self.guard("x::set-output name=a::b\twhy\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(out, "skipped=xset-outputnameab\n")

    def test_the_guard_runs_before_anything_is_marked_green(self):
        text = MIRROR_WF.read_text()
        lines = text.splitlines()
        guard = lines.index(GUARD)
        mark = lines.index("      - name: mark phase 2 green")
        self.assertLess(guard, mark)
        head = "\n".join(lines[guard:guard + 4])
        self.assertIn("id: ran-all", head)
        self.assertIn("if: success() && needs.plan.outputs.bench == 'phase2'", head)
        # Both green steps need every earlier step, the guard included, to
        # have succeeded.
        tail = "\n".join(lines[mark:])
        self.assertEqual(tail.count("if: success() && needs.plan.outputs.bench == 'phase2'"), 2)

    def test_the_status_names_the_skipped_suites(self):
        text = MIRROR_WF.read_text()
        self.assertIn("      skipped: ${{ steps.ran-all.outputs.skipped }}", text)
        self.assertIn("          SKIPPED: ${{ needs.bench.outputs.skipped }}", text)
        self.assertIn('[ -z "$SKIPPED" ] || desc="phase 2 not proven, skipped: $SKIPPED', text)
        self.assertIn('-f description="${desc:0:140}"', text)


if __name__ == "__main__":
    unittest.main()
