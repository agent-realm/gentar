"""TOML scenario schema v1 — load + validate.

A scenario states the subject, the bench agent, the ORACLE (the
no-LLM reference solution, run verbatim), and VERIFY assertions
checked against reality. Agent-mode decisions render in phase 3;
oracle mode is phase 2's runner.

    [scenario]
    name = "…"                # defaults to filename stem
    subject = "kommander-playbook"   # dir under the subjects root
    agent = "shell"           # oracle runs on a plain sandbox
    template = "gentar-bench-v1"  # optional: sbx template to create from
    bench = "tart"           # optional: bench tier override (sbx default);
                              # tart = template names a local tart VM
    credentials = ["ANTHROPIC_API_KEY"]  # env var NAMES the run needs;
                                          # missing → refuse (exit 2) before
                                          # any bench exists; values travel
                                          # to the bench, names never values
                                          # to spans/reports

    [oracle]
    steps = ["…", "…"]        # shell lines; each must exit 0

    [[verify.files]]
    path = "~/.claude-playbooks/kommander/CLAUDE.md"

    [[verify.commands]]
    command = "claude-playbook info kommander"
    contains = "Version:"     # optional substring check

    A verify probe carrying the stub value "TODO" (emitted by
    `gentar subject init`) is an unfilled scaffold: the suite loads,
    but `run` refuses with exit 2 before any bench exists.

Validation is STRICT (s4 hardening, from the d2-tweaker/d3-abuser
drills): every table is type-checked, every key outside the schema is
a ScenarioError (a renamed probe key is a config error, never a
silently-ignored assertion), empty-string probes are errors (a probe
asserting nothing), and an oracle scenario with zero verify probes and
no driver "asserts nothing" — it loads, but `run` refuses with exit 2
before any bench exists, exactly like an unfilled stub. Malformed TOML
is a ScenarioError carrying file + decoder message, never a traceback.
"""

import tomllib
from pathlib import Path

# Sentinel for an unfilled verify probe, as emitted by the
# `gentar subject init` scaffold. A scenario carrying any stub still
# LOADS (so `coordinator ls` sees it) but `coordinator run` refuses
# with exit 2 before any bench exists — an honest scaffold, never a
# fake-green one.
STUB = "TODO"

# Schema closure — every legal key per table. A key outside its set is
# a ScenarioError naming both the key and the legal set: typos and
# renames surface as config errors instead of silently-ignored probes.
_SCENARIO_KEYS = {"name", "subject", "agent", "template", "bench", "credentials"}
_ORACLE_KEYS = {"steps"}
_VERIFY_KEYS = {"files", "commands"}
_FILE_KEYS = {"path", "contains"}
_COMMAND_KEYS = {"command", "contains"}
_DRIVER_KEYS = {"command", "turns"}
_TURN_KEYS = {"type", "prompt", "send", "pattern", "label", "tries", "timeout"}
_BUDGET_KEYS = {"tokens", "simulate_spend"}


class ScenarioError(ValueError):
    pass


def _check_keys(table: dict, legal: set[str], where: str, path: Path) -> None:
    unknown = sorted(set(table) - legal)
    if unknown:
        raise ScenarioError(
            f"{path}: unknown key(s) {', '.join(unknown)} in {where} — "
            f"legal keys: {', '.join(sorted(legal))}")


def _table(doc: dict, key: str, path: Path) -> dict:
    val = doc.get(key)
    if val is None:
        return {}
    if not isinstance(val, dict):
        raise ScenarioError(f"{path}: [{key}] must be a TOML table, got {type(val).__name__}")
    _check_keys(val, {"scenario": _SCENARIO_KEYS, "oracle": _ORACLE_KEYS,
                      "verify": _VERIFY_KEYS, "driver": _DRIVER_KEYS,
                      "budget": _BUDGET_KEYS}[key], f"[{key}]", path)
    return val


class TomlScenario:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with open(path, "rb") as fh:
                doc = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ScenarioError(f"{path}: malformed TOML — {exc}") from exc

        sc = _table(doc, "scenario", path)
        self.name = sc.get("name", path.stem)
        self.subject = sc.get("subject")
        self.agent = sc.get("agent", "shell")
        self.template = sc.get("template")  # sbx template tag / tart VM name
        # Bench tier override: "tart" = macOS VM bench (default per config
        # otherwise, i.e. the sbx tier).
        self.bench = sc.get("bench")
        for key, val in (("name", self.name), ("subject", self.subject),
                         ("agent", self.agent), ("template", self.template),
                         ("bench", self.bench)):
            if val is not None and not isinstance(val, str):
                raise ScenarioError(f"{path}: scenario.{key} must be a string")
        self.credentials = list(sc.get("credentials", []))
        for i, c in enumerate(self.credentials):
            if not isinstance(c, str) or not c.strip():
                raise ScenarioError(
                    f"{path}: scenario.credentials[{i}] must be an env var name")

        oracle = _table(doc, "oracle", path)
        steps = oracle.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(s, str) for s in steps):
            raise ScenarioError(f"{path}: [oracle].steps must be a list of shell lines")
        self.steps = list(steps)

        verify = _table(doc, "verify", path)
        files = verify.get("files", [])
        commands = verify.get("commands", [])
        for probe_list, where, must_key in ((files, "verify.files", "path"),
                                            (commands, "verify.commands", "command")):
            if not isinstance(probe_list, list):
                raise ScenarioError(f"{path}: {where} must be a list of tables")
            for i, f in enumerate(probe_list):
                if not isinstance(f, dict):
                    raise ScenarioError(f"{path}: {where}[{i}] must be a table")
                _check_keys(f, _FILE_KEYS if must_key == "path" else _COMMAND_KEYS,
                            f"{where}[{i}]", path)
                if must_key not in f:
                    raise ScenarioError(f"{path}: {where}[{i}] missing {must_key}")
                for k, v in f.items():
                    if not isinstance(v, str) or not v.strip():
                        raise ScenarioError(
                            f"{path}: {where}[{i}].{k} must be a non-empty string "
                            f"(an empty probe asserts nothing)")
        self.files = list(files)
        self.commands = list(commands)

        driver = _table(doc, "driver", path)
        self.driver_command = driver.get("command")
        if self.driver_command is not None and not isinstance(self.driver_command, str):
            raise ScenarioError(f"{path}: [driver].command must be a string")
        turns = driver.get("turns", [])
        if not isinstance(turns, list):
            raise ScenarioError(f"{path}: [driver].turns must be a list of tables")
        self.turns = list(turns)

        # Spend ceiling in "spend units" (tokens today). 0 = unbudgeted.
        budget = _table(doc, "budget", path)
        for key in ("tokens", "simulate_spend"):
            val = budget.get(key, 0)
            if not isinstance(val, int) or isinstance(val, bool):
                raise ScenarioError(f"{path}: [budget].{key} must be an integer")
        self.budget_tokens = int(budget.get("tokens", 0) or 0)
        # Simulated spend for no-LLM runs exercising the budget guard:
        # after a passing run this many units are recorded as burned.
        self.simulated_spend = int(budget.get("simulate_spend", 0) or 0)

        if not self.steps and not self.driver_command:
            raise ScenarioError(f"{path}: needs [oracle].steps or a [driver] command")
        for i, t in enumerate(self.turns):
            if not isinstance(t, dict):
                raise ScenarioError(f"{path}: driver.turns[{i}] must be a table")
            _check_keys(t, _TURN_KEYS, f"driver.turns[{i}]", path)
            kind = t.get("type")
            if kind not in ("answer", "expect", "pick", "abort"):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}].type must be answer|expect|pick|abort")
            if kind in ("answer", "expect") and not t.get(("prompt" if kind == "answer" else "pattern")):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing prompt/pattern")
            if kind == "pick" and not t.get("label"):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing label")

        # Unfilled scaffold stubs: verify probes still carrying the
        # TODO sentinel. Loaded fine (ls lists the suite); the run-time
        # stub guard in coordinator.run refuses them before any bench
        # exists. Descriptors name the exact probe to fill.
        self.stubs: list[str] = []
        for i, f in enumerate(self.files):
            if f["path"] == STUB or f.get("contains") == STUB:
                self.stubs.append(f"verify.files[{i}]")
        for i, c in enumerate(self.commands):
            if c["command"] == STUB or c.get("contains") == STUB:
                self.stubs.append(f"verify.commands[{i}]")

        # Asserts-nothing: an oracle suite with zero verify probes and
        # no driver has nothing to check — running it could only print a
        # vacuous "0/0 assertions passed". Driver suites are exempt
        # (the driver's own outcome is the verdict). Loads fine; the
        # run-time guard in coordinator.run refuses it before any bench
        # exists, exactly like an unfilled stub.
        self.asserts_nothing: bool = (
            not self.files and not self.commands and not self.driver_command)

    def describe(self) -> str:
        parts = [f"subject={self.subject or '-'}", f"agent={self.agent}",
                 f"steps={len(self.steps)}", f"verify={len(self.files)}f/{len(self.commands)}c"]
        return " ".join(parts)


def load_dir(scenarios_dir: str | Path) -> dict[str, TomlScenario]:
    out: dict[str, TomlScenario] = {}
    for path in sorted(Path(scenarios_dir).glob("*.toml")):
        scenario = TomlScenario(path)
        out[scenario.name] = scenario
    return out
