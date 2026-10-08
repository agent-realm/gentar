"""verify-ref.sh admits only commits the public repository's own refs reach.

2026-10-08 (D5, the pilot's "fix it"; root's cpb design): a private mirror
runs a public repository's phase 2 on a self-hosted runner. GitHub serves
any commit of a fork network by sha through the parent's URL, so a fetch
that succeeds proves nothing. The fixture here is a server repository that
does the same (uploadpack.allowAnySHA1InWant): a commit that only a
refs/pull/1/head points at IS fetchable by sha, and must still be refused.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "subject-template" / "mirror" / "arena" / "verify-ref.sh"


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


class Server:
    """A 'public repository' with main, a v* tag, a branch, a fork PR ref."""

    def __init__(self, tmp):
        self.url = str(tmp / "srv.git")
        git("init", "-q", "--bare", self.url)
        git("-C", self.url, "symbolic-ref", "HEAD", "refs/heads/trunk")
        git("-C", self.url, "config", "uploadpack.allowAnySHA1InWant", "true")
        w = str(tmp / "w")
        git("init", "-q", w)

        def commit(msg):
            git("-C", w, "commit", "-q", "--allow-empty", "-m", msg)
            return git("-C", w, "rev-parse", "HEAD")

        git("-C", w, "checkout", "-q", "-b", "trunk")
        self.old = commit("old trunk")
        self.head = commit("trunk head")
        git("-C", w, "push", "-q", self.url, "trunk")
        # a release cut from a branch that is gone: reachable from its tag only
        git("-C", w, "checkout", "-q", "-b", "release", self.old)
        self.tagged = commit("release fix")
        git("-C", w, "tag", "-a", "v1.0.1", "-m", "v1.0.1")
        git("-C", w, "tag", "other-tag")
        git("-C", w, "push", "-q", self.url, "refs/tags/v1.0.1", "refs/tags/other-tag")
        self.other_tag_only = self.tagged    # same commit; the v* tag is what admits it
        git("-C", w, "checkout", "-q", "-b", "untagged", self.old)
        self.only_other_tag = commit("only a non-v tag")
        git("-C", w, "tag", "not-a-release")
        git("-C", w, "push", "-q", self.url, "refs/tags/not-a-release")
        # a collaborator's branch
        git("-C", w, "checkout", "-q", "-b", "feature", self.head)
        self.branch = commit("feature work")
        git("-C", w, "push", "-q", self.url, "feature")
        # a fork's pull request: only refs/pull/1/head points at it
        git("-C", w, "checkout", "-q", "-b", "fork", self.head)
        self.fork = commit("fork work")
        git("-C", w, "push", "-q", self.url, "HEAD:refs/pull/1/head")


@unittest.skipUnless(VERIFY.exists(), "the kit is not in the image build context")
class VerifyRefTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.srv = Server(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def verify(self, *args, url=None):
        out = self.tmp / "gh-output"
        out.unlink(missing_ok=True)
        r = subprocess.run(["/bin/bash", str(VERIFY), *args[:-1], url or self.srv.url, args[-1]]
                           if args else ["/bin/bash", str(VERIFY), url or self.srv.url],
                           capture_output=True, text=True,
                           env={**os.environ, "GITHUB_OUTPUT": str(out)})
        return r, (out.read_text() if out.exists() else "")

    def admitted(self, sha, via, *flags):
        r, out = self.verify(*flags, sha)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"sha={sha}\nvia={via}\n")
        self.assertEqual(out, r.stdout)

    def refused(self, sha, *flags):
        r, out = self.verify(*flags, sha)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"verify-ref: refusing {sha} -- not reachable from", r.stderr)
        self.assertEqual((r.stdout, out), ("", ""))
        return r

    def test_the_fixture_serves_a_fork_commit_by_sha(self):
        # The premise: fetching the fork's sha through the parent works.
        d = self.tmp / "probe.git"
        git("init", "-q", "--bare", str(d))
        git("-C", str(d), "fetch", "-q", self.srv.url, self.srv.fork)
        self.assertEqual(git("-C", str(d), "cat-file", "-t", self.srv.fork), "commit")

    def test_default_branch_commits_are_admitted(self):
        self.admitted(self.srv.head, "refs/heads/trunk")
        self.admitted(self.srv.old, "refs/heads/trunk")

    def test_no_sha_is_the_default_branch_head(self):
        r, out = self.verify()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"sha={self.srv.head}\nvia=refs/heads/trunk\n")

    def test_a_commit_only_a_v_tag_reaches_is_admitted(self):
        self.admitted(self.srv.tagged, "refs/tags/v1.0.1")

    def test_a_commit_only_another_tag_reaches_is_refused(self):
        self.refused(self.srv.only_other_tag)

    def test_a_branch_head_needs_the_flag(self):
        self.refused(self.srv.branch)
        self.admitted(self.srv.branch, "refs/heads/feature", "--allow-branch-heads")
        self.admitted(self.srv.head, "refs/heads/trunk", "--allow-branch-heads")

    def test_a_fork_commit_is_refused_although_fetchable(self):
        self.refused(self.srv.fork)
        self.refused(self.srv.fork, "--allow-branch-heads")

    def test_an_unknown_sha_is_refused(self):
        self.refused("0" * 40)

    def test_bad_input_is_a_usage_refusal(self):
        for sha in (self.srv.head[:12], self.srv.head.upper(), "main", "HEAD~1", self.srv.head + "0"):
            with self.subTest(sha=sha):
                r, _ = self.verify(sha)
                self.assertEqual(r.returncode, 2, r.stderr)
        r, _ = self.verify(self.srv.head, url="--upload-pack=touch /tmp/x")
        self.assertEqual(r.returncode, 2)

    def test_an_unreadable_repository_is_a_refusal_not_an_admission(self):
        r, out = self.verify(self.srv.head, url=str(self.tmp / "nowhere.git"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(out, "")

    def test_it_is_self_contained(self):
        # A mirror vendors this one file (D5): nothing sourced, no kit path.
        text = VERIFY.read_text()
        for word in ("source ", ". \"$", "$(dirname", "plan.py", "run.sh"):
            self.assertNotIn(word, text)

    def test_only_heads_and_v_tags_are_ever_fetched(self):
        text = VERIFY.read_text()
        self.assertNotIn("refs/pull", text.split("set -euo pipefail", 1)[1])
        self.assertNotIn("--filter", text)


if __name__ == "__main__":
    unittest.main()
