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
                              # tart = template names a local tart VM;
                              # osb/daytona = template is an image ref
    credentials = ["ANTHROPIC_API_KEY"]  # env var NAMES the run needs;
                                          # entries are ALTERNATIVES and a
                                          # list entry is an all-of group:
                                          # ["KEY", ["TOKEN","BASE_URL"]] =
                                          # the key alone or the token+
                                          # endpoint pair, nothing less;
                                          # no group fully present → refuse
                                          # (exit 2) before any bench exists;
                                          # values travel to the bench,
                                          # names never values to
                                          # spans/reports
    pass_env = ["ANTHROPIC_DEFAULT_SONNET_MODEL"]  # OPTIONAL non-secret
                                          # knobs forwarded when set, no
                                          # guard — unset means default
                                          # (e.g. a cheaper model pin)

    [oracle]
    steps = ["…", "…"]        # shell lines; each must exit 0

    [driver]                  # alternative to oracle: an interactive
    command = "…"             # command at the bench pty, driven by turns
    [[driver.turns]]          # kinds: answer (await prompt, type text),
    type = "expect"           # expect (await pattern), pick (walk the
    pattern = "…"             # ❯ picker to a label), abort (prove the
                              # danger gate), key (raw \r/\x03 events —
                              # the only Enter a TUI registers; optional
                              # `after` pattern anchors the keys to a
                              # screen so they cannot race the render
                              # onto the next dialog's default)

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


def credentials_satisfied(groups: list[list[str]], get) -> bool:
    """True when at least one alternative group is FULLY present — the
    guard's whole rule, pure so it is testable without a run. `get` is
    an env lookup (os.environ.get)."""
    return any(all(get(name) for name in g) for g in groups)


class TomlScenario:
    def __init__(self, path: Path) -> None:
        self.path = path
        with open(path, "rb") as fh:
            doc = tomllib.load(fh)

        sc = doc.get("scenario") or {}
        self.name = sc.get("name", path.stem)
        self.subject = sc.get("subject")
        self.agent = sc.get("agent", "shell")
        self.template = sc.get("template")  # sbx template tag / tart VM name / image ref
        # Bench tier override: "tart" = macOS VM bench, "osb"/"daytona" =
        # container bench (template = image ref; default per config
        # otherwise, i.e. the sbx tier).
        self.bench = sc.get("bench")
        # Entries are ALTERNATIVE providers; an entry may be a single env
        # var name or a LIST of names that must travel together — a token
        # without its endpoint is half a provider (PR #26 review: the old
        # any-of guard let the pair half-pass and start a misconfigured
        # credentialed bench instead of refusing).
        self.credentials = list(sc.get("credentials", []))
        for i, entry in enumerate(self.credentials):
            names = entry if isinstance(entry, list) else [entry]
            if (not names
                    or any(not isinstance(n, str) or not n.strip() for n in names)
                    or any(isinstance(n, list) for n in names)):
                raise ScenarioError(
                    f"{path}: scenario.credentials[{i}] must be an env "
                    f"var name or a flat list of them (a group that "
                    f"travels together)")
        # Optional non-secret env knobs (e.g. a model pin). Forwarded to the
        # bench when present, never guarded — unlike credentials, absence is
        # a legitimate "use the default", not a usage error.
        self.pass_env = list(sc.get("pass_env", []))
        for i, c in enumerate(self.pass_env):
            if not isinstance(c, str) or not c.strip():
                raise ScenarioError(
                    f"{path}: scenario.pass_env[{i}] must be an env var name")

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
            if kind not in ("answer", "expect", "pick", "abort", "key"):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}].type must be "
                    f"answer|expect|pick|abort|key")
            if kind in ("answer", "expect") and not t.get(("prompt" if kind == "answer" else "pattern")):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing prompt/pattern")
            if kind == "pick" and not t.get("label"):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing label")
            if kind == "key":
                keys = t.get("keys") or ([t["key"]] if t.get("key") else [])
                if not keys:
                    raise ScenarioError(f"{path}: driver.turns[{i}] missing key/keys")
                from gentar.pty_driver import _KEYS
                bad = [k for k in keys if k not in _KEYS]
                if bad:
                    raise ScenarioError(
                        f"{path}: driver.turns[{i}] unknown key(s) "
                        f"{', '.join(map(repr, bad))} — supported: "
                        f"{' '.join(sorted(_KEYS))}")
                if "after" in t and not (isinstance(t["after"], str) and t["after"].strip()):
                    raise ScenarioError(
                        f"{path}: driver.turns[{i}].after must be a "
                        f"non-empty screen pattern")
            if "optional" in t and not isinstance(t["optional"], bool):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}].optional must be a boolean "
                    f"(skip the turn when its screen never shows)")
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

    def credential_groups(self) -> list[list[str]]:
        """Declared credentials as ALTERNATIVES: one group per entry —
        a str entry is a group of one, a list entry an all-of group."""
        return [e if isinstance(e, list) else [e] for e in self.credentials]

    def credential_names(self) -> list[str]:
        """Flat env-var names (forwarding, reports, spans) — the group
        structure is guard-only and never reaches the record."""
        return [n for g in self.credential_groups() for n in g]


def load_dir(scenarios_dir: str | Path) -> dict[str, TomlScenario]:
    out: dict[str, TomlScenario] = {}
    for path in sorted(Path(scenarios_dir).glob("*.toml")):
        scenario = TomlScenario(path)
        out[scenario.name] = scenario
    return out
