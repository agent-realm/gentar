"""bin/pr-scan: a pull request may not add environment data or a credential.

gentar is public, and what a pull request adds is published with it. The
scan runs on every pull request (gentar.yml, job `scan`) over the lines the
PR adds and its commit messages, and prints where a finding is and its
class, never the text. Every synthetic value below is assembled at run
time, so this file is not a finding itself.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PR_SCAN = ROOT / "bin" / "pr-scan"
WORKFLOW = ROOT / ".github" / "workflows" / "gentar.yml"
ALLOWLIST = ROOT / ".github" / "scan-allowlist.toml"


def j(*parts: str) -> str:
    return "".join(parts)


SAMPLES = {
    "private-ip": [j("10.", "0.0.7"), j("172.", "20.1.2"), j("192.", "168.1.9")],
    "home-path": [j("/ho", "me/alice/src"), j("/Us", "ers/bob")],
    "key-shape": [j("gh", "p_", "a" * 36), j("sk-", "ant-", "x" * 24),
                  j("AK", "IA", "ABCDEFGHIJKLMNOP"), j("-----BEGIN ", "OPENSSH PRIVATE KEY-----")],
    "model-route": [j("glm", "-5.1"), j("9", "router"), j("deepseek", "-v4"), j("port ", "2012", "8")],
}
STAND_INS = ["192.0.2.10", "198.51.100.7", "203.0.113.5", "/home/user/src", "/home/runner/work",
             "/Users/user", "/home/u/.config", "example-host", "user@example-host",
             "python 3.12.4", "v0.10.1", "11.0.0.1", "172.32.0.1", "glm-"]


@unittest.skipUnless(PR_SCAN.exists(), "bin/ is not in this build context")
class PrScanTest(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.commit({"README.md": "base\n"}, "base")
        self.base = self.rev()
        self.git("checkout", "-q", "-b", "pr")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false", *args],
            cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def rev(self, ref="HEAD"):
        return self.git("rev-parse", ref).strip()

    def commit(self, files, message="change"):
        for name, text in files.items():
            p = self.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.rev()

    def scan(self, *args, **env):
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.repo), **env}
        argv = list(args) or ["--base", self.base, "--head", self.rev()]
        return subprocess.run([sys.executable, str(PR_SCAN), *argv], cwd=self.repo,
                              capture_output=True, text=True, env=e)

    def assertNoValue(self, r, values):
        for v in values:
            self.assertNotIn(v, r.stdout + r.stderr)

    def test_each_class_fails_on_a_synthetic_value_and_never_prints_it(self):
        values = [(c, v) for c, vs in SAMPLES.items() for v in vs]
        self.commit({"notes.txt": "".join(f"see {v} here\n" for _, v in values)})
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        want = [f"notes.txt:{i}: {c}" for i, (c, _) in enumerate(values, 1)]
        self.assertEqual(r.stdout.splitlines(), want)
        self.assertIn(f"{len(values)} finding(s)", r.stderr)
        self.assertNoValue(r, [v for _, v in values])

    def test_stand_ins_pass(self):
        self.commit({"docs/x.md": "".join(f"{v}\n" for v in STAND_INS)})
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pr-scan: clean", r.stdout)

    def test_a_commit_message_fails_too_and_shows_only_where(self):
        ip = SAMPLES["private-ip"][0]
        sha = self.commit({"a.txt": "fine\n"}, f"subject\n\nreached the bench at {ip}")
        r = self.scan()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines(), [f"commit {sha[:12]} message:3: private-ip"])
        self.assertNoValue(r, [ip])

    def test_only_what_the_pr_adds_counts(self):
        ip = SAMPLES["private-ip"][1]
        self.git("checkout", "-q", "main")
        self.commit({"old.txt": "".join(f"line {i}\n" for i in range(1, 6)) + f"host {ip}\n"})
        self.base = self.rev()
        self.git("checkout", "-q", "-B", "pr", "main")
        # an untouched line already on the base, an edit beside it, and a deletion
        lines = (self.repo / "old.txt").read_text().splitlines()
        lines[0] = "line one"
        self.commit({"old.txt": "\n".join(lines) + "\n"})
        self.assertEqual(self.scan().returncode, 0)
        self.commit({"old.txt": "line one\n"})
        self.assertEqual(self.scan().returncode, 0)

    def test_line_numbers_are_the_new_files(self):
        self.commit({"f.txt": "".join(f"{i}\n" for i in range(1, 11))})
        self.base = self.rev()
        lines = [str(i) for i in range(1, 11)]
        lines[6] = SAMPLES["home-path"][0]
        lines.insert(2, "inserted")
        self.commit({"f.txt": "\n".join(lines) + "\n"})
        self.assertEqual(self.scan().stdout.splitlines(), ["f.txt:8: home-path"])

    def test_main_merged_into_the_pr_brings_no_findings(self):
        self.commit({"pr.txt": "pr work\n"})
        self.git("checkout", "-q", "main")
        self.commit({"main.txt": f"{SAMPLES['private-ip'][2]}\n"}, "on main since the branch")
        self.base = self.rev()
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def allow(self, entries):
        body = "".join(
            "[[allow]]\n" + "".join(f"{k} = '{v}'\n" for k, v in e.items()) + "\n" for e in entries)
        (self.repo / ".github").mkdir(exist_ok=True)
        (self.repo / ".github" / "scan-allowlist.toml").write_text(body)

    def test_an_allowlisted_fixture_passes_only_where_it_is_allowed(self):
        key = SAMPLES["key-shape"][1]
        self.allow([{"path": "tests/test_*.py", "class": "key-shape",
                     "line": re.escape(f'SECRET = "{key}"'), "reason": "synthetic fixture"}])
        self.commit({"tests/test_x.py": f'SECRET = "{key}"\n'})
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # the same value elsewhere, another shape in the file, another class: findings
        other_key = SAMPLES["key-shape"][0]
        ip = SAMPLES["private-ip"][0]
        self.commit({"docs/x.md": f"{key}\n",
                     "tests/test_x.py": f'SECRET = "{key}"\nOTHER = "{other_key}"\nHOST = "{ip}"\n'})
        r = self.scan()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(sorted(r.stdout.splitlines()),
                         ["docs/x.md:1: key-shape", "tests/test_x.py:2: key-shape",
                          "tests/test_x.py:3: private-ip"])
        self.assertNoValue(r, [key, other_key, ip])

    def test_an_allowlist_entry_covers_the_whole_line_only(self):
        # Codex, on a copy of this scanner: with search(), a private address
        # appended to an allowlisted fixture line was hidden by the fixture's own match
        fixture = f'NETS = "{j("10.", "0.0.0/8")}"'
        ip = SAMPLES["private-ip"][2]
        self.allow([{"path": "conf.txt", "class": "private-ip",
                     "line": re.escape(fixture), "reason": "synthetic fixture"}])
        self.commit({"conf.txt": f"{fixture}\n"})
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.commit({"conf.txt": f"{fixture}\n{fixture[:-1]},{ip}\"\n{fixture} # {ip}\n"})
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["conf.txt:2: private-ip", "conf.txt:3: private-ip"])
        self.assertNoValue(r, [ip])

    def test_a_file_git_calls_binary_is_still_scanned(self):
        # Codex, on a copy of this scanner: a NUL byte made git print
        # "Binary files ... differ", no line was read, and the scan said clean
        key = SAMPLES["key-shape"][0]
        ip = SAMPLES["private-ip"][0]
        (self.repo / "blob.bin").write_bytes(b"\x00\x01head\n" + f"token {key}\n".encode())
        self.commit({".gitattributes": "*.dat binary\n", "notes.dat": f"host {ip}\n"})
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(sorted(r.stdout.splitlines()), ["blob.bin:2: key-shape", "notes.dat:1: private-ip"])
        self.assertNoValue(r, [key, ip])

    def test_an_allowlist_entry_needs_a_reason_and_a_known_class(self):
        self.allow([{"path": "*", "class": "key-shape", "line": "x", "reason": " "}])
        self.commit({"a.txt": "fine\n"})
        r = self.scan()
        self.assertEqual(r.returncode, 2)
        self.assertIn("lacks reason", r.stderr)
        self.allow([{"path": "*", "class": "everything", "line": "x", "reason": "no"}])
        r = self.scan()
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown class", r.stderr)

    def test_annotations_name_the_place_and_the_class_only(self):
        ip = SAMPLES["private-ip"][0]
        self.commit({"bin/pr-scan": f"{ip}\n"})
        r = self.scan(GITHUB_ACTIONS="true")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error file=bin/pr-scan,line=1::private-ip (the matched text is not shown)",
                      r.stdout)
        self.assertIn("::warning::this pull request changes the scan itself (bin/pr-scan)", r.stdout)
        self.assertNoValue(r, [ip])

    def test_a_line_is_split_at_newlines_only(self):
        # Codex on #104: splitlines() broke an added line at \v, \f, U+2028
        # (and text mode at a lone \r), and the rest was never scanned
        ip = SAMPLES["private-ip"][0]
        seps = ["\v", "\f", "\u2028", "\r", "\x1c", "\x1e"]
        self.commit({"odd.txt": "".join(f"header{sep}{ip}\n" for sep in seps)})
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines(),
                         [f"odd.txt:{i}: private-ip" for i in range(1, len(seps) + 1)])
        self.assertNoValue(r, [ip])

    def test_a_record_separator_in_a_commit_message_hides_nothing(self):
        # Codex on #104: a \x1e inside a message was read as a commit boundary
        ip = SAMPLES["private-ip"][1]
        msg = self.repo.parent / f"{self.repo.name}.msg"
        self.addCleanup(lambda: msg.unlink(missing_ok=True))
        msg.write_text(f"subject\n\nbefore\x1eafter {ip}\n")
        (self.repo / "a.txt").write_text("fine\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-F", str(msg))
        r = self.scan()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines(), [f"commit {self.rev()[:12]} message:3: private-ip"])
        self.assertNoValue(r, [ip])

    def test_a_change_that_only_deletes_from_the_scan_still_warns(self):
        # Codex on #104: the warning came from added lines, so deleting a
        # pattern or an allowlist entry, and adding nothing, went unflagged
        self.git("checkout", "-q", "main")
        self.commit({"bin/pr-scan": "pattern one\npattern two\n",
                     ".github/scan-allowlist.toml": "# entries\n"})
        self.base = self.rev()
        self.git("checkout", "-q", "-B", "pr", "main")
        self.commit({"bin/pr-scan": "pattern one\n"})
        r = self.scan(GITHUB_ACTIONS="true")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::this pull request changes the scan itself (bin/pr-scan)", r.stdout)
        self.git("rm", "-q", ".github/scan-allowlist.toml")
        self.git("commit", "-q", "-m", "drop the allowlist")
        r = self.scan()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("changes the scan itself (.github/scan-allowlist.toml, bin/pr-scan)", r.stderr)

    def test_usage(self):
        self.assertEqual(self.scan("--base", self.base).returncode, 2)
        self.assertEqual(self.scan("--files", "README.md", "--base", self.base).returncode, 2)
        self.assertEqual(self.scan("--base", "nonexistent", "--head", "HEAD").returncode, 2)


@unittest.skipUnless(PR_SCAN.exists() and WORKFLOW.exists(), "bin/ and .github/ are not here")
class WiringTest(unittest.TestCase):

    def test_the_workflow_scans_every_pull_request(self):
        text = WORKFLOW.read_text()
        job = text[text.index("\n  scan:\n"):]
        self.assertIn("name: scan (added lines)", job)
        self.assertIn("if: github.event_name == 'pull_request'", job)
        self.assertIn("runs-on: ubuntu-latest", job)
        self.assertIn("fetch-depth: 0", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("BASE: ${{ github.event.pull_request.base.sha }}", job)
        self.assertIn("HEAD: ${{ github.event.pull_request.head.sha }}", job)
        self.assertIn('python3 bin/pr-scan --base "$BASE" --head "$HEAD"', job)

    def test_every_allowlist_entry_is_explained_and_still_used(self):
        import tomllib
        entries = tomllib.loads(ALLOWLIST.read_text())["allow"]
        self.assertTrue(entries)
        for e in entries:
            with self.subTest(path=e["path"]):
                self.assertTrue(e["reason"].strip())
                files = sorted(ROOT.glob(e["path"]))
                self.assertTrue(files, "the allowlisted file is gone")
                rx = re.compile(e["line"])
                used = [l for f in files for l in f.read_text().splitlines() if rx.fullmatch(l)]
                self.assertTrue(used, "no line matches the entry any more")
                # and the entry is needed: without it, those lines are findings of its class
                r = subprocess.run([sys.executable, str(PR_SCAN), "--allowlist", os.devnull,
                                    "--files", *map(str, files)],
                                   capture_output=True, text=True, cwd=ROOT)
                self.assertIn(f": {e['class']}", r.stdout)

    def test_the_scans_own_files_are_clean(self):
        files = [PR_SCAN, ALLOWLIST, WORKFLOW, Path(__file__).resolve()]
        r = subprocess.run([sys.executable, str(PR_SCAN), "--files", *map(str, files)],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
