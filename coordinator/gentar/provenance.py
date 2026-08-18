"""Run provenance — ported from gauntlet run.sh run_attrs_json.

A run_id alone makes two runs DISTINGUISHABLE; it does not make them
COMPARABLE. Without these fields a duration that moved between runs
cannot be attributed: did the subject change, did the engine change,
did the scenario definition change, was something else competing for
the bench-host? Each field answers one of those.

Gauntlet's set is adapted where its VM-era fields had no gentar
analogue: channel/server/uninstall/agent_mode (VM-clone install
decisions) collapse into agent/template/template_digest/bench_host,
and subject_sha hashes the subject TREE (subjects are mounted dirs,
not git checkouts, inside the coordinator).
"""

import hashlib
import os
from pathlib import Path

from gentar.config import Config
from gentar.toml_scenario import TomlScenario


def subject_fingerprint(subject_dir: str) -> tuple[str, bool]:
    """(short content hash, dirty?) for a mounted subject dir. The hash
    covers relpath + bytes of every file (sorted) — two runs of "the
    same" subject are only comparable if the bytes were identical.
    dirty=True when the dir doesn't exist (nothing pushed)."""
    root = Path(subject_dir) if subject_dir else None
    if root is None or not root.is_dir():
        # No subject (arena builtins) or a push that never happened —
        # never hash Path("") (== cwd) by accident.
        return "", bool(subject_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:12], False


def scenario_fingerprint(scenario: TomlScenario) -> str:
    """Content hash of the scenario definition — the decisions, not the
    path. Raw bytes (trailing newline preserved), like gauntlet's
    _ch_sha_file."""
    try:
        return hashlib.sha256(scenario.path.read_bytes()).hexdigest()[:12]
    except (OSError, AttributeError):
        return "builtin"


def run_attrs(scenario: TomlScenario | None, cfg: Config,
              scenario_name: str, run_kind: str,
              concurrency: int = 1, template_digest: str = "") -> dict:
    subject_dir = (f"{cfg.subjects_root}/{scenario.subject}"
                   if scenario and scenario.subject else "")
    subj_sha, subj_dirty = subject_fingerprint(subject_dir)
    return {
        "subject_dir":     subject_dir,
        "subject_sha":     subj_sha,
        "subject_dirty":   subj_dirty,
        "engine_sha":      cfg.engine_sha,
        "engine_dirty":    bool(cfg.engine_dirty),
        "config":          (scenario.path.name if scenario and hasattr(scenario, "path")
                            else f"{scenario_name}.py"),
        "config_sha256":   scenario_fingerprint(scenario) if scenario else "builtin",
        "agent":           scenario.agent if scenario else "shell",
        "template":        scenario.template if scenario and scenario.template else "",
        "template_digest": template_digest,
        # Wall-clock durations are meaningless without knowing how many
        # other scenarios were competing for the same bench-host.
        "concurrency":     concurrency,
        "bench_host":      cfg.bench_host,
        "driver_host":     os.uname().nodename,
        "run_kind":        run_kind,
    }
