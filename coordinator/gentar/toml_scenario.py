"""TOML scenario schema v1 — load + validate.

A scenario states the subject, the bench agent, the ORACLE (the
no-LLM reference solution, run verbatim), and VERIFY assertions
checked against reality. Agent-mode decisions render in phase 3;
oracle mode is phase 2's runner.

    [scenario]
    name = "…"                # defaults to filename stem
    subject = "kommander-playbook"   # dir under the subjects root
    agent = "shell"           # oracle runs on a plain sandbox

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

        self.steps = list((doc.get("oracle") or {}).get("steps", []))
        verify = doc.get("verify") or {}
        self.files = list(verify.get("files", []))
        self.commands = list(verify.get("commands", []))

        if not self.steps:
            raise ScenarioError(f"{path}: [oracle].steps must not be empty")
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
