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
"""

import tomllib
from pathlib import Path


class ScenarioError(ValueError):
    pass


class TomlScenario:
    def __init__(self, path: Path) -> None:
        self.path = path
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)

        sc = doc.get("scenario") or {}
        self.name = sc.get("name", path.stem)
        self.subject = sc.get("subject")
        self.agent = sc.get("agent", "shell")
        self.template = sc.get("template")  # sbx template tag, e.g. gentar-bench-v1
        self.credentials = list(sc.get("credentials", []))
        for i, c in enumerate(self.credentials):
            if not isinstance(c, str) or not c.strip():
                raise ScenarioError(
                    f"{path}: scenario.credentials[{i}] must be an env var name")

        self.steps = list((doc.get("oracle") or {}).get("steps", []))
        verify = doc.get("verify") or {}
        self.files = list(verify.get("files", []))
        self.commands = list(verify.get("commands", []))

        driver = doc.get("driver") or {}
        self.driver_command = driver.get("command")
        self.turns = list(driver.get("turns", []))

        # Spend ceiling in "spend units" (tokens today). 0 = unbudgeted.
        budget = doc.get("budget") or {}
        self.budget_tokens = int(budget.get("tokens", 0) or 0)
        # Simulated spend for no-LLM runs exercising the budget guard:
        # after a passing run this many units are recorded as burned.
        self.simulated_spend = int(budget.get("simulate_spend", 0) or 0)

        if not self.steps and not self.driver_command:
            raise ScenarioError(f"{path}: needs [oracle].steps or a [driver] command")
        for i, t in enumerate(self.turns):
            kind = t.get("type")
            if kind not in ("answer", "expect", "pick", "abort"):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}].type must be answer|expect|pick|abort")
            if kind in ("answer", "expect") and not t.get(("prompt" if kind == "answer" else "pattern")):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing prompt/pattern")
            if kind == "pick" and not t.get("label"):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing label")
        for i, f in enumerate(self.files):
            if "path" not in f:
                raise ScenarioError(f"{path}: verify.files[{i}] missing path")
        for i, c in enumerate(self.commands):
            if "command" not in c:
                raise ScenarioError(f"{path}: verify.commands[{i}] missing command")

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
