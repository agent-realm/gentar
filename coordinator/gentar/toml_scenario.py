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

s6 hardening (d1-tweaker/d2-abuser/d3-impatient drills): the exit-2
net has no holes (recursion bombs and unreadable paths are config
errors too), bench tier / credentials list / non-empty name / negative
budget values are validated at load, a driver suite with zero turns
asserts nothing (the s4 exemption was wholesale; `command = "true"`
ran green through it), and duplicate scenario names in one dir name
BOTH files instead of silently shadowing.
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
        # s6 hardening (d2-abuser drill): the exit-2 net must have no
        # holes. A recursion-bomb TOML (deeply nested arrays) raises
        # RecursionError; anything unreadable (a directory named *.toml,
        # permissions) raises OSError. Both are config errors here —
        # never a traceback, never exit 1.
        except RecursionError as exc:
            raise ScenarioError(
                f"{path}: TOML nests too deeply to parse — config error, "
                f"not a crash") from exc
        except OSError as exc:
            raise ScenarioError(f"{path}: unreadable — {exc}") from exc

        sc = _table(doc, "scenario", path)
        self.name = sc.get("name", path.stem)
        self.subject = sc.get("subject")
        self.agent = sc.get("agent", "shell")
        self.template = sc.get("template")  # sbx template tag / tart VM name
        # Bench tier override: "tart" = macOS VM bench (default per config
        # otherwise, i.e. the sbx tier). s6 hardening (d1-tweaker drill):
        # validated AT LOAD — a typo'd tier must be a config error at `ls`
        # time, not a traceback at `run` time.
        self.bench = sc.get("bench")
        for key, val in (("name", self.name), ("subject", self.subject),
                         ("agent", self.agent), ("template", self.template),
                         ("bench", self.bench)):
            if val is not None and not isinstance(val, str):
                raise ScenarioError(f"{path}: scenario.{key} must be a string")
        # s6 hardening (d1-tweaker drill): an empty name registers as a
        # ghost — blank line in `ls`, empty entry in known lists, runnable
        # by `run ""`. Every other string field demands non-empty; so does
        # the name.
        if self.name is not None and not self.name.strip():
            raise ScenarioError(
                f"{path}: scenario.name must be a non-empty string "
                f"(empty names register as ghosts)")
        if self.bench not in (None, "", "sbx", "tart"):
            raise ScenarioError(
                f"{path}: scenario.bench must be 'sbx' or 'tart', got "
                f"{self.bench!r}")
        # s6 hardening (d1-tweaker drill): a bare string here spells its
        # letters as env var names ("A, N, T, …") — refuse the wrong TYPE
        # at load, naming the file and the key.
        raw_credentials = sc.get("credentials", [])
        if not isinstance(raw_credentials, list):
            raise ScenarioError(
                f"{path}: scenario.credentials must be a LIST of env var "
                f"names, e.g. credentials = [\"ANTHROPIC_API_KEY\"] "
                f"(got {type(raw_credentials).__name__})")
        self.credentials = list(raw_credentials)
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
        # s6 hardening (d2-abuser drill): negatives are a config error —
        # a negative ceiling or negative spend is arithmetic vandalism,
        # not a budget.
        budget = _table(doc, "budget", path)
        for key in ("tokens", "simulate_spend"):
            val = budget.get(key, 0)
            if not isinstance(val, int) or isinstance(val, bool):
                raise ScenarioError(f"{path}: [budget].{key} must be an integer")
            if val < 0:
                raise ScenarioError(
                    f"{path}: [budget].{key} must be >= 0, got {val}")
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
        # vacuous "0/0 assertions passed". s6 hardening (d1-tweaker +
        # d2-abuser drills): a DRIVER suite with zero turns and zero
        # verify probes asserts nothing either — the s4 exemption was
        # wholesale ("driver's outcome is the verdict"), but a driver
        # with no turns HAS no outcome; `command = "true"` ran green
        # through that door. The verdict evidence is turns or probes;
        # zero of both is the same vacuous green. Loads fine; the
        # run-time guard in coordinator.run refuses it before any bench
        # exists, exactly like an unfilled stub.
        self.asserts_nothing: bool = (
            not self.files and not self.commands
            and not (self.driver_command and self.turns))

    def describe(self) -> str:
        parts = [f"subject={self.subject or '-'}", f"agent={self.agent}",
                 f"steps={len(self.steps)}", f"verify={len(self.files)}f/{len(self.commands)}c"]
        return " ".join(parts)


def load_dir(scenarios_dir: str | Path) -> dict[str, TomlScenario]:
    """Load every *.toml in a scenarios dir. s6 hardening (d1-tweaker
    drill): a directory named *.toml is a config error (not an
    IsADirectory traceback), and two files declaring the same scenario
    name in one dir is a config error naming BOTH files — one silently
    winning over the other is a shadowing bug, not a feature."""
    out: dict[str, TomlScenario] = {}
    seen: dict[str, Path] = {}
    for path in sorted(Path(scenarios_dir).glob("*.toml")):
        if path.is_dir():
            raise ScenarioError(f"{path}: is a directory, not a scenario file")
        scenario = TomlScenario(path)
        if scenario.name in seen:
            raise ScenarioError(
                f"{path}: duplicate scenario name {scenario.name!r} "
                f"(also declared by {seen[scenario.name]})")
        seen[scenario.name] = path
        out[scenario.name] = scenario
    return out
