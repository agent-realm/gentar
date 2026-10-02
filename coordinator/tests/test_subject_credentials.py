"""No credential rides into a bench inside a subject's git metadata.

Found 2026-10-02 (Sonnet 5.5's review, verified): gentar's nightly cloned
subjects with the token in the URL, git saved it in .git/config, and the
engine copied the subject, .git included, into benches where agents run with
skipped permissions. The engine now refuses such a subject before any bench
exists; the workflow passes the token as an env-config header instead.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.config import Config

SECRET = "ghp_SECRETVALUE1234567890"


def subject(config_text=None, extra=None):
    d = Path(tempfile.mkdtemp()) / "subj"
    (d / ".git").mkdir(parents=True)
    if config_text is not None:
        (d / ".git" / "config").write_text(config_text)
    for name, body in (extra or {}).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)
    return d


CLEAN = '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/o/r\n'


class ProblemsTest(unittest.TestCase):

    def test_a_clean_clone_passes(self):
        self.assertEqual(coord.subject_credential_problems(str(subject(CLEAN))), [])

    def test_a_token_in_the_remote_url_is_refused(self):
        bad = CLEAN.replace("https://github.com", f"https://x-access-token:{SECRET}@github.com")
        why = coord.subject_credential_problems(str(subject(bad)))
        self.assertTrue(any("remote URL" in w for w in why))
        self.assertNotIn(SECRET, " ".join(why))

    def test_a_user_password_url_is_refused(self):
        bad = CLEAN.replace("https://github.com", "https://bob:hunter2@git.example.org")
        self.assertTrue(coord.subject_credential_problems(str(subject(bad))))

    def test_actions_checkout_auth_header_is_refused(self):
        bad = CLEAN + '[http "https://github.com/"]\n\textraheader = AUTHORIZATION: basic ' + SECRET + "\n"
        why = coord.subject_credential_problems(str(subject(bad)))
        self.assertTrue(any("extraheader" in w for w in why))
        self.assertNotIn(SECRET, " ".join(why))

    def test_a_credential_store_is_refused(self):
        for name in (".git-credentials", ".git/credentials"):
            why = coord.subject_credential_problems(str(subject(CLEAN, {name: SECRET})))
            self.assertTrue(any("credential store" in w for w in why), name)

    def test_a_worktree_pointer_and_no_git_at_all_pass(self):
        d = Path(tempfile.mkdtemp()) / "wt"
        d.mkdir()
        (d / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n")
        self.assertEqual(coord.subject_credential_problems(str(d)), [])
        e = Path(tempfile.mkdtemp())
        self.assertEqual(coord.subject_credential_problems(str(e)), [])

    def test_an_ssh_remote_is_fine(self):
        ok = CLEAN.replace("https://github.com/o/r", "git@github.com:o/r.git")
        self.assertEqual(coord.subject_credential_problems(str(subject(ok))), [])


class GuardTest(unittest.TestCase):

    def test_a_credentialed_subject_is_exit_2_and_no_bench(self):
        d = subject(CLEAN.replace("https://github.com", f"https://x-access-token:{SECRET}@github.com"))
        sc = mock.Mock(subject="subj", credentials=[], bench="", uses_judge=False,
                       budget_tokens=0, driller=None, warnings=[])
        env = {"GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u", "GENTAR_REPORT_DIR": "",
               "GENTAR_SUBJECTS_ROOT": str(d.parent)}
        printed = []
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config()
            with mock.patch.object(coord, "_resolve", return_value=(lambda *a, **k: "", sc)), \
                 mock.patch.object(coord, "make_bench") as mk, \
                 mock.patch.object(coord, "Spans"), \
                 mock.patch("builtins.print", side_effect=printed.append):
                rc = coord._run("s", cfg)
        self.assertEqual(rc, 2)
        mk.assert_not_called()
        out = "\n".join(map(str, printed))
        self.assertIn("subject guard", out)
        self.assertNotIn(SECRET, out)


class WorkflowTest(unittest.TestCase):

    def test_the_workflow_never_puts_the_token_in_a_url_or_the_script(self):
        wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "gentar.yml"
        if not wf.exists():
            self.skipTest("the workflow is not in this build context")
        text = wf.read_text()
        self.assertNotIn("x-access-token:${{", text)
        self.assertNotIn('"${{ secrets.GENTAR_SUBJECT_TOKEN }}"', text)
        self.assertEqual(text.count("SUBJECT_TOKEN: ${{ secrets.GENTAR_SUBJECT_TOKEN }}"), 2)
        self.assertEqual(text.count('GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"'), 2)


if __name__ == "__main__":
    unittest.main()
