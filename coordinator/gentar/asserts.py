"""Assertion engine v1 — verdicts from reality (gauntlet vocabulary,
Python port). Everything runs IN the bench through the installed state;
nothing is asserted from the harness's own filesystem.

Vocabulary: file-exists · file-contains · cmd-exit · cmd-contains.
(sql-count and text-in-transcript join in phases 3/5.)
"""

from dataclasses import dataclass

from gentar.benchhost import BenchHost


@dataclass
class AssertResult:
    name: str
    ok: bool
    detail: str = ""


def _sh(bench: BenchHost, sandbox: str, command: str) -> tuple[int, str]:
    return bench.exec(sandbox, command)


def check_files(bench: BenchHost, sandbox: str, home: str,
                files: list[dict]) -> list[AssertResult]:
    results = []
    for f in files:
        path = f["path"].replace("~", home, 1)
        contains = f.get("contains")
        if contains is None:
            rc, _ = _sh(bench, sandbox, f"test -e {path!r}")
            results.append(AssertResult(
                f"file-exists {path}", rc == 0, "" if rc == 0 else "missing"))
        else:
            rc, out = _sh(bench, sandbox, f"grep -F -- {contains!r} {path!r}")
            results.append(AssertResult(
                f"file-contains {path}", rc == 0,
                "" if rc == 0 else f"pattern {contains!r} not found"))
    return results


def check_commands(bench: BenchHost, sandbox: str,
                   commands: list[dict]) -> list[AssertResult]:
    results = []
    for c in commands:
        command, contains = c["command"], c.get("contains")
        rc, out = _sh(bench, sandbox, command)
        ok, detail = rc == 0, f"exit {rc}: {out.strip()[:300]}"
        if ok and contains is not None:
            ok = contains in out
            detail = "" if ok else f"output lacks {contains!r}: {out.strip()[:300]}"
        results.append(AssertResult(f"cmd {command[:60]}", ok, detail))
    return results
