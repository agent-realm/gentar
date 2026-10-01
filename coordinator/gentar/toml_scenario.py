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

# Annotations as strings: this module is imported by dryrun.py on the
# HOST, where python may be 3.9 (stock macOS). `list[str] | None` in a
# signature is evaluated at def time on 3.9 and raises TypeError; with
# this it never evaluates. The coordinator image is 3.12 and does not
# care either way.
from __future__ import annotations

try:
    import tomllib                      # 3.11+
except ModuleNotFoundError:             # 3.9/3.10: stock macOS, old distros
    # tomli IS tomllib — the stdlib module was adopted from it, so this is
    # the same parser under its pre-stdlib name, not a second
    # implementation that could disagree about what a scenario means.
    # Only host-side callers (dryrun.py) ever land here: the coordinator
    # image is python:3.12-slim and always takes the import above.
    import tomli as tomllib             # type: ignore[no-redef]
from pathlib import Path
import re

# A credential or pass_env entry is an ENVIRONMENT VARIABLE NAME. Anything
# else can never be set by a shell, so the suite could never be satisfied —
# and the kit's shell-side readers (run.sh --sweep, credential forwarding)
# rely on it: with names confined to this alphabet, no `#`, `]` or quote
# can appear inside one, which is what lets a line-oriented awk parse the
# array exactly as TOML does. Refusing here makes that an invariant, not a
# hope.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class ScenarioError(ValueError):
    pass


def satisfied_group(groups: list[list[str]], get) -> list[str] | None:
    """The FIRST fully-present alternative group, or None when none is
    complete. Declaration order is the preference order, and the result
    is also what may be FORWARDED: a name outside the winning group is a
    stray half-provider, not a credential this run chose (PR #26 review
    round 3 — a set ANTHROPIC_BASE_URL rode along with a winning
    ANTHROPIC_API_KEY and redirected it). Pure so the guard's whole rule
    is testable without a run; `get` is an env lookup (os.environ.get)."""
    for g in groups:
        if all(get(name) for name in g):
            return list(g)
    return None



def dropped_credentials(groups: list[list[str]], get) -> list[str]:
    """Declared names that ARE set but will NOT be forwarded, because they
    sit outside the winning group. Forwarding only the winner is correct —
    it is what stops a stray endpoint redirecting a key — but doing it
    silently turns a schema mistake into a failure three layers away.

    The case that made this necessary (the first real adopter,
    claude-playbooks): `credentials = ["ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL"]` parses fine and reads like a pair, but a flat
    list is ALTERNATIVES — so the token won alone, the set base URL was
    dropped without a word, and the agent reported "Invalid API key" from
    inside the bench. Written `[["ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL"]]` it is one group and both travel. Nothing is
    dropped when no group wins: the guard refuses that run instead."""
    won = satisfied_group(groups, get)
    if won is None:
        return []
    seen, out = set(won), []
    for g in groups:
        for name in g:
            if name not in seen and get(name):
                seen.add(name)
                out.append(name)
    return out

def credentials_satisfied(groups: list[list[str]], get) -> bool:
    """True when at least one alternative group is FULLY present — the
    guard's rule as a predicate."""
    return satisfied_group(groups, get) is not None


def _check_soft_judge(path, i, j) -> None:
    """[[verify.judge]]: a yes/no question about the final screen, reported only."""
    where = f"{path}: verify.judge[{i}]"
    if not isinstance(j, dict):
        raise ScenarioError(f"{where} must be a table")
    unknown = set(j) - {"question", "true", "false", "p_min", "p_max_no"}
    if unknown:
        raise ScenarioError(f"{where}: unknown key(s) {sorted(unknown)}")
    if not isinstance(j.get("question"), str) or not j["question"].strip():
        raise ScenarioError(f"{where}.question must be a non-empty string")
    p_min, p_no = j.get("p_min", 0.9), j.get("p_max_no", 0.2)
    if not isinstance(p_min, (int, float)) or not 0.5 < p_min <= 1:
        raise ScenarioError(f"{where}.p_min must be in (0.5, 1]")
    if not isinstance(p_no, (int, float)) or not 0 <= p_no < p_min:
        raise ScenarioError(f"{where}.p_max_no must be in [0, p_min)")


def _check_judge(path, i, j) -> None:
    """A semantic expect: one narrow yes/no question about the screen."""
    where = f"{path}: driver.turns[{i}].judge"
    if not isinstance(j, dict):
        raise ScenarioError(f"{where} must be a table: {{ question = \"…\", p_min = 0.9 }}")
    unknown = set(j) - {"question", "true", "false", "p_min", "p_max_no", "hold", "every"}
    if unknown:
        raise ScenarioError(f"{where}: unknown key(s) {sorted(unknown)}")
    if not isinstance(j.get("question"), str) or not j["question"].strip():
        raise ScenarioError(f"{where}.question must be a non-empty string")
    for k in ("true", "false"):
        if k in j and not isinstance(j[k], str):
            raise ScenarioError(f"{where}.{k} must be a string (what counts as {k})")
    p_min = j.get("p_min", 0.9)
    p_max_no = j.get("p_max_no", 0.2)
    if not isinstance(p_min, (int, float)) or not 0.5 < p_min <= 1:
        raise ScenarioError(f"{where}.p_min must be in (0.5, 1]")
    if not isinstance(p_max_no, (int, float)) or not 0 <= p_max_no < p_min:
        raise ScenarioError(f"{where}.p_max_no must be in [0, p_min)")
    hold = j.get("hold", 2)
    if not isinstance(hold, int) or isinstance(hold, bool) or hold < 2:
        raise ScenarioError(
            f"{where}.hold must be an integer >= 2 — a judged turn never passes on a "
            f"single yes (identical requests can get different answers)")
    every = j.get("every", 3)
    if not isinstance(every, (int, float)) or every <= 0:
        raise ScenarioError(f"{where}.every must be a positive number of seconds")


GOAL_RESERVED = ("wait", "done", "stuck")
_ACTION_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")


def _check_goal(path, sc) -> None:
    """A goal pilot: one goal, a closed list of actions, nothing else."""
    from gentar.keys import KEYS
    where = f"{path}: driver"
    if not isinstance(sc.goal, str) or not sc.goal.strip():
        raise ScenarioError(f"{where}.goal must be a non-empty string when actions are declared")
    if sc.turns:
        raise ScenarioError(f"{where}: a goal pilot has no scripted turns — use one or the other")
    if not sc.actions:
        raise ScenarioError(f"{where}.actions: a goal pilot needs its closed set of actions")
    for name, v, ok in (("max_steps", sc.max_steps, isinstance(sc.max_steps, int) and 1 <= sc.max_steps <= 200),
                        ("p_act", sc.p_act, isinstance(sc.p_act, (int, float)) and 0.5 < sc.p_act <= 1),
                        ("every", sc.goal_every, isinstance(sc.goal_every, (int, float)) and sc.goal_every > 0),
                        ("timeout", sc.goal_timeout, isinstance(sc.goal_timeout, (int, float)) and sc.goal_timeout > 0)):
        if isinstance(v, bool) or not ok:
            raise ScenarioError(f"{where}.{name} is out of range: {v!r}")
    seen = set()
    for i, a in enumerate(sc.actions):
        w = f"{where}.actions[{i}]"
        if not isinstance(a, dict):
            raise ScenarioError(f"{w} must be a table")
        unknown = set(a) - {"id", "when", "send", "key", "then", "approve", "on"}
        if unknown:
            raise ScenarioError(f"{w}: unknown key(s) {sorted(unknown)}")
        aid = a.get("id")
        if not isinstance(aid, str) or not _ACTION_ID.match(aid) or aid in GOAL_RESERVED:
            raise ScenarioError(f"{w}.id must be [a-z][a-z0-9_]* and not one of {GOAL_RESERVED}")
        if aid in seen:
            raise ScenarioError(f"{w}.id {aid!r} is declared twice")
        seen.add(aid)
        if not isinstance(a.get("when"), str) or not a["when"].strip():
            raise ScenarioError(f"{w}.when must say when the action applies")
        if ("send" in a) == ("key" in a):
            raise ScenarioError(f"{w} needs exactly one of `send` (literal text) or `key`")
        if "send" in a and not isinstance(a["send"], str):
            raise ScenarioError(f"{w}.send must be a string (typed as given — the judge never writes)")
        if "key" in a and a["key"] not in KEYS:
            raise ScenarioError(f"{w}.key must be one of {' '.join(sorted(KEYS))}")
        if "then" in a and a["then"] != "enter":
            raise ScenarioError(f"{w}.then may only be \"enter\"")
        if "approve" in a and not isinstance(a["approve"], bool):
            raise ScenarioError(f"{w}.approve must be true or false")
        if a.get("approve"):
            on = a.get("on")
            if not isinstance(on, str) or not on.strip():
                raise ScenarioError(
                    f"{w}: an approving action needs `on`, a regex anchoring the one screen "
                    f"it may approve — approval is never offered on an unanticipated screen")
            try:
                re.compile(on)
            except re.error as exc:
                raise ScenarioError(f"{w}.on is not a valid regex: {exc}") from None
        elif "on" in a:
            raise ScenarioError(f"{w}.on is only for approving actions (approve = true)")


_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}", "!"}
_PREFIXES = {"exec", "nohup", "env", "sudo", "command", "time"}


def plain_timeout(command: str, depth: int = 0) -> bool:
    """True when `command` starts something under GNU `timeout` without
    `--foreground`. timeout puts its child in a NEW background process group,
    so an interactive program under it is stopped by SIGTTIN (state T) the
    moment it reads the tty, before it draws anything; headless `-p` runs
    never notice (cockpit's first-run scenario, 2026-10-01).

    Only `timeout` in command position counts (`echo timeout` does not), and
    a quoted script (`bash -lc "timeout 60 claude"`) is looked into."""
    import re
    import shlex
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|(){}!")
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return False
    prev = None
    for i, w in enumerate(words):
        command_pos = (prev is None or prev in _SEPARATORS or prev in _PREFIXES
                       or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", prev or "") is not None)
        if command_pos and w.rsplit("/", 1)[-1] == "timeout" and i + 1 < len(words):
            # options before the duration; -k/-s (and the long forms without
            # `=`) take the next word as their argument
            opts, rest = [], iter(words[i + 1:])
            for o in rest:
                if not o.startswith("-"):
                    break
                opts.append(o)
                if o in ("-k", "-s", "--kill-after", "--signal"):
                    next(rest, None)
            if "--foreground" not in opts:
                return True
        if depth < 3 and any(c.isspace() for c in w) and plain_timeout(w, depth + 1):
            return True
        prev = w
    return False


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
        # What kind of data the scenario touches. "synthetic" is the only
        # value that lets a semantic turn send a screen to a judge (pilot,
        # 2026-09-26); anything else, or nothing, keeps every screen inside
        # the arena. Checked by the coordinator before any bench exists.
        self.data = sc.get("data", "")
        if not isinstance(self.data, str):
            raise ScenarioError(f"{path}: scenario.data must be a string (\"synthetic\")")
        # The judge key is the COORDINATOR's; declaring it would forward it
        # into the bench, where the agent under test could read it.
        for field in ("credentials", "pass_env"):
            flat = [n for e in (sc.get(field) or []) for n in (e if isinstance(e, list) else [e])]
            if "TYPESAFE_API_KEY" in flat:
                raise ScenarioError(
                    f"{path}: scenario.{field} names TYPESAFE_API_KEY — the judge key "
                    f"stays with the coordinator and is never forwarded to a bench")
        # Judge limits (only read when a turn uses a judge).
        judge = doc.get("judge") or {}
        self.judge_max_calls = int(judge.get("max_calls", 200))
        self.judge_max_input_tokens = int(judge.get("max_input_tokens", 500_000))
        self.judge_lines = int(judge.get("lines", 40))
        if not 1 <= self.judge_lines <= 40:
            raise ScenarioError(
                f"{path}: judge.lines must be 1..40 — the pilot's egress rule sends at "
                f"most the last 40 content rows of the screen")
        # Entries are ALTERNATIVE providers; an entry may be a single env
        # var name or a LIST of names that must travel together — a token
        # without its endpoint is half a provider (PR #26 review: the old
        # any-of guard let the pair half-pass and start a misconfigured
        # credentialed bench instead of refusing).
        self.credentials = list(sc.get("credentials", []))
        for i, entry in enumerate(self.credentials):
            names = entry if isinstance(entry, list) else [entry]
            if (not names
                    or any(not isinstance(n, str) or not _ENV_NAME.match(n) for n in names)
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
            if not isinstance(c, str) or not _ENV_NAME.match(c):
                raise ScenarioError(
                    f"{path}: scenario.pass_env[{i}] must be an env var name "
                    f"([A-Za-z_][A-Za-z0-9_]*), got {c!r}")

        self.steps = list((doc.get("oracle") or {}).get("steps", []))
        # Diagnostics run on the bench when a driver turn fails, before the
        # session is closed: their output lands in the report's failure
        # snapshot (cockpit). Never a verdict; same timeout rule as verify.
        on_failure = doc.get("on_failure") or {}
        if not isinstance(on_failure, dict) or set(on_failure) - {"commands"}:
            raise ScenarioError(f"{path}: [on_failure] takes only `commands`")
        self.on_failure = []
        for i, c in enumerate(on_failure.get("commands", [])):
            c = {"command": c} if isinstance(c, str) else c
            if (not isinstance(c, dict) or not isinstance(c.get("command"), str)
                    or not c["command"].strip() or set(c) - {"command", "timeout"}
                    or isinstance(c.get("timeout", 60), bool)
                    or not isinstance(c.get("timeout", 60), int)
                    or not 1 <= c.get("timeout", 60) <= 600):
                raise ScenarioError(
                    f"{path}: on_failure.commands[{i}] must be a command string or "
                    f"{{ command = \"...\", timeout = 1..600 }}")
            self.on_failure.append(c)
        verify = doc.get("verify") or {}
        self.files = list(verify.get("files", []))
        self.commands = list(verify.get("commands", []))
        # Soft judgments of the final screen: reported, never the verdict.
        self.judge_checks = list(verify.get("judge", []))

        driver = doc.get("driver") or {}
        self.driver_command = driver.get("command")
        self.turns = list(driver.get("turns", []))
        # A goal-driven pilot: a goal and a CLOSED set of actions; the judge
        # picks one action per step from the screen (README, Goal pilots).
        self.goal = driver.get("goal", "")
        self.actions = list(driver.get("actions", []))
        self.max_steps = driver.get("max_steps", 25)
        self.p_act = driver.get("p_act", 0.8)
        self.goal_every = driver.get("every", 2)
        self.goal_timeout = driver.get("timeout", 300)
        if self.goal or self.actions:
            _check_goal(path, self)
        # Not refusals: things that load fine and are probably wrong. The
        # coordinator prints them and puts them in the report.
        self.warnings: list[str] = []
        if self.driver_command and (self.turns or self.goal) and plain_timeout(self.driver_command):
            self.warnings.append(
                "driver.command runs under plain `timeout`: GNU timeout puts its child "
                "in a background process group, so an interactive program is stopped "
                "by SIGTTIN (state T) on its first tty read and never draws. Use "
                "`timeout --foreground`")
        # Rates over N runs — for judged suites only: a deterministic suite
        # must pass every time, so a rate would only hide its flakes.
        semantic = doc.get("semantic") or {}
        self.semantic_runs = semantic.get("runs", 1)
        self.pass_rate_min = semantic.get("pass_rate_min", 1.0)

        # Spend ceiling in "spend units" (tokens today). 0 = unbudgeted.
        budget = doc.get("budget") or {}
        self.budget_tokens = int(budget.get("tokens", 0) or 0)
        # Simulated spend for no-LLM runs exercising the budget guard:
        # after a passing run this many units are recorded as burned.
        self.simulated_spend = int(budget.get("simulate_spend", 0) or 0)

        if self.on_failure and not self.driver_command:
            raise ScenarioError(f"{path}: [on_failure] needs a [driver]: it runs when a turn fails")
        if not self.steps and not self.driver_command:
            raise ScenarioError(f"{path}: needs [oracle].steps or a [driver] command")
        for i, t in enumerate(self.turns):
            kind = t.get("type")
            if kind not in ("answer", "expect", "pick", "abort", "key"):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}].type must be "
                    f"answer|expect|pick|abort|key")
            if kind == "expect" and ("pattern" in t) == ("judge" in t):
                raise ScenarioError(
                    f"{path}: driver.turns[{i}] (expect) needs exactly one of "
                    f"`pattern` (a regex) or `judge` (a semantic question)")
            if kind == "expect" and "judge" in t:
                _check_judge(path, i, t["judge"])
            elif kind in ("answer", "expect") and not t.get(("prompt" if kind == "answer" else "pattern")):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing prompt/pattern")
            if kind == "pick" and not t.get("label"):
                raise ScenarioError(f"{path}: driver.turns[{i}] missing label")
            if kind == "key":
                keys = t.get("keys") or ([t["key"]] if t.get("key") else [])
                if not keys:
                    raise ScenarioError(f"{path}: driver.turns[{i}] missing key/keys")
                from gentar.keys import KEYS as _KEYS
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
        for i, j in enumerate(self.judge_checks):
            _check_soft_judge(path, i, j)
        if self.judge_checks and not self.driver_command:
            raise ScenarioError(f"{path}: verify.judge needs a [driver] — it judges the final screen")
        if (isinstance(self.semantic_runs, bool) or not isinstance(self.semantic_runs, int)
                or not 1 <= self.semantic_runs <= 20):
            raise ScenarioError(f"{path}: semantic.runs must be an integer 1..20")
        if (isinstance(self.pass_rate_min, bool) or not isinstance(self.pass_rate_min, (int, float))
                or not 0 < self.pass_rate_min <= 1):
            raise ScenarioError(f"{path}: semantic.pass_rate_min must be in (0, 1]")
        if (self.semantic_runs > 1 or self.pass_rate_min < 1) and not self.uses_judge:
            raise ScenarioError(
                f"{path}: [semantic] runs / pass_rate_min are for judged suites only — a "
                f"deterministic suite must pass every time")
        for i, f in enumerate(self.files):
            if "path" not in f:
                raise ScenarioError(f"{path}: verify.files[{i}] missing path")
        for i, c in enumerate(self.commands):
            if "command" not in c:
                raise ScenarioError(f"{path}: verify.commands[{i}] missing command")

    @property
    def uses_judge(self) -> bool:
        return (bool(self.goal) or bool(self.judge_checks)
                or any("judge" in t for t in self.turns))

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
