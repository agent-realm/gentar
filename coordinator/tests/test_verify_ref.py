"""verify-ref.sh admits only commits the public repository's own refs reach.

2026-10-08 (D5, the pilot's "fix it"; root's cpb design): a private mirror
runs a public repository's phase 2 on a self-hosted runner. GitHub serves
any commit of a fork network by sha through the parent's URL, so a fetch
that succeeds proves nothing. The fixture here is a server repository that
does the same (uploadpack.allowAnySHA1InWant): a commit that only a
refs/pull/1/head points at IS fetchable by sha, and must still be refused.
"""

import json
import os
import shutil
import subprocess
import sys
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



# git, plus a writer that keeps filling the clone after `fetch` returns, as a
# detached `git maintenance run --auto` can
FAKE_GIT = """#!/bin/sh
"$REAL_GIT" "$@"; rc=$?
if [ "$1" = -C ] && case " $* " in *" fetch "*) true ;; *) false ;; esac; then
  "$PYTHON" "$WRITER" "$2" "$BUSY_SECONDS" "$MARK" >/dev/null 2>&1 </dev/null &
  n=0; while [ ! -e "$MARK" ] && [ $n -lt 200 ]; do sleep 0.05; n=$((n+1)); done
fi
exit $rc
"""
WRITER = """import os, sys, time
clone, secs, mark = sys.argv[1], float(sys.argv[2]), sys.argv[3]
end, i = time.monotonic() + secs, 0
while time.monotonic() < end:
    try:
        open(os.path.join(clone, "objects", "busy.%d" % (i % 1000)), "w").close()
    except OSError:
        break                       # the clone is gone
    if i == 0:
        open(mark, "w").close()
    i += 1
"""
FAKE_RM = """#!/bin/sh
echo "rm: cannot remove: Directory not empty" >&2
exit 1
"""


@unittest.skipUnless(VERIFY.exists(), "the kit is not in the image build context")
class CleanupTest(unittest.TestCase):
    """Removing the temporary clone never changes the verdict. A private
    mirror's gate admitted a commit and then exited 1: rm found the clone
    "not empty", because git's detached auto-maintenance was still writing
    into it, and `set -e` made the EXIT trap's failing rm the script's
    status."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.srv = Server(cls.tmp)
        cls.real_git = shutil.which("git")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_verify(self, sha, bindir=None, **env):
        tmpdir = Path(tempfile.mkdtemp(dir=self.tmp))
        out = tmpdir.parent / f"{tmpdir.name}.out"
        path = f"{bindir}:{os.environ['PATH']}" if bindir else os.environ["PATH"]
        r = subprocess.run(["/bin/bash", str(VERIFY), self.srv.url, sha],
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PATH": path, "TMPDIR": str(tmpdir),
                                "GITHUB_OUTPUT": str(out), **env})
        return r, (out.read_text() if out.exists() else ""), tmpdir

    def bindir(self, **scripts):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        for name, text in scripts.items():
            (d / name).write_text(text)
            (d / name).chmod(0o755)
        return d

    def busy(self, sha):
        d = self.bindir(git=FAKE_GIT)
        (d / "writer.py").write_text(WRITER)
        mark = d / "writer.started"
        r, out, tmpdir = self.run_verify(sha, d, REAL_GIT=self.real_git, PYTHON=sys.executable,
                                         WRITER=str(d / "writer.py"), BUSY_SECONDS="1",
                                         MARK=str(mark))
        self.assertTrue(mark.exists(), "the writer never started: the test proves nothing")
        return r, out, tmpdir

    def test_a_busy_clone_does_not_fail_an_admitted_commit(self):
        r, out, tmpdir = self.busy(self.srv.head)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"sha={self.srv.head}\nvia=refs/heads/trunk\n")
        self.assertEqual(out, r.stdout)
        self.assertNotIn("left behind", r.stderr)
        self.assertEqual(list(tmpdir.iterdir()), [])          # removed once it went quiet

    def test_a_busy_clone_does_not_admit_a_refused_commit(self):
        # and is removed: exit 1 alone would also pass with the old trap,
        # whose failing rm exited 1 too
        r, out, tmpdir = self.busy(self.srv.fork)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((r.stdout, out), ("", ""))
        self.assertNotIn("left behind", r.stderr)
        self.assertEqual(list(tmpdir.iterdir()), [])

    def test_a_clone_that_will_not_go_keeps_the_verdict(self):
        d = self.bindir(rm=FAKE_RM)
        for sha, rc in ((self.srv.head, 0), (self.srv.fork, 1)):
            with self.subTest(rc=rc):
                r, out, tmpdir = self.run_verify(sha, d)
                self.assertEqual(r.returncode, rc, r.stderr)
                self.assertIn("verify-ref: could not remove", r.stderr)
                self.assertIn("left behind", r.stderr)
                self.assertEqual(bool(out), rc == 0)
                [left] = tmpdir.iterdir()                     # left, as the warning says
                self.assertTrue(left.name.startswith("verify-ref."))

    def test_nothing_in_the_cleanup_sets_the_exit_status(self):
        # Even its own warning failing (stderr closed) leaves an admission 0:
        # under `set -e` any failing command in the trap would set the status.
        d = self.bindir(rm=FAKE_RM)
        r = subprocess.run(["/bin/bash", "-c", 'exec 2>&-; exec /bin/bash "$0" "$@"',
                            str(VERIFY), self.srv.url, self.srv.head],
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PATH": f"{d}:{os.environ['PATH']}",
                                "TMPDIR": str(Path(tempfile.mkdtemp(dir=self.tmp)))})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, f"sha={self.srv.head}\nvia=refs/heads/trunk\n")

    def test_git_starts_no_automatic_maintenance(self):
        trace = self.tmp / "trace2.json"
        trace.unlink(missing_ok=True)
        r, _, _ = self.run_verify(self.srv.head, GIT_TRACE2_EVENT=str(trace))
        self.assertEqual(r.returncode, 0, r.stderr)
        children = [e.get("argv", []) for e in map(json.loads, trace.read_text().splitlines())
                    if e.get("event") == "child_start"]
        self.assertTrue(any("upload-pack" in " ".join(a) for a in children), children)  # traced
        self.assertEqual([a for a in children if "maintenance" in a or "gc" in a], [])


if __name__ == "__main__":
    unittest.main()
