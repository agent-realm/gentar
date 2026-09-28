"""Drillers: persona agents that wear a hat, have no target, and report.

A suite asserts; a goal pilot pursues one goal; a driller wanders the
subject as a character would (the white hat security professional first)
and tells us what it noticed. Its feedback is the product, so the feedback
is never the verdict. A driller run passes or fails on hard facts only: the
boundary audit below. What it says goes into the report as typed,
evidence-backed findings, ranked by how many of N runs found the same thing.

This module is the bench-free core. Everything here is decided from data
(the environment, the sbx policy table, the sbx policy log, the transcript)
so it is tested without a bench:

  start_refusals   what stops a driller run before any bench exists (exit 2),
                   from `sbx policy ls --json` and `sbx policy check
                   network <canary> --json` (host_problems)
  sandbox_problems per-sandbox rules the brief did not ask for (sbx kits)
  policy_argv      the per-sandbox allow rule for a deny-by-default host
                   (none at all by default: the model is called by the
                   coordinator, never from inside the bench)
  audit            the sbx policy log read after the run: denied = finding,
                   allowed off the allowlist = BREACH (the run fails)
  outside_changes  the bench host's sandboxes/templates before vs after
  extract          feedback -> typed findings (BAML, on our own model route)
  supported        drop a finding whose evidence the transcript does not show
  cluster          the same finding across N runs, ranked by frequency

The boundary is enforced by infrastructure, not by the persona prompt: sbx
cannot narrow one sandbox below a global `allow **`, so a driller refuses
such a host. On a deny-by-default host (`sbx policy init deny-all`) a
per-sandbox allow does open exactly its hosts (proven on VM 151: the allowed
host answered 200, every other host got sbx's 403).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field

# Boundary's hosted Studio: setting it makes BAML ship prompts and outputs to
# their cloud. Never set, and its presence refuses the run, whatever value.
FORBIDDEN_ENV = ("BOUNDARY_API_KEY",)

# Names that must never reach a driller's bench, whatever a brief says. By
# CLASS, not by list: every coordinator-owned name carries one of these
# prefixes (bench, clone, OTLP, Daytona, OSB, driller model, judge), and a
# list missed GENTAR_DAYTONA_API_KEY and GENTAR_OSB_API_KEY (Codex). A new
# arena key is covered the day it is added.
NEVER_FORWARD_PREFIXES = ("GENTAR_", "BENCH_", "TYPESAFE_", "BOUNDARY_")


def never_forward(name: str) -> bool:
    return name.upper().startswith(NEVER_FORWARD_PREFIXES)

SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class DrillerRefusal(RuntimeError):
    """A driller run that must not start: exit 2, before any bench."""


@dataclass(frozen=True)
class Persona:
    key: str
    hat: str
    charter: str


WHITE_HAT = Persona(
    key="white-hat",
    hat="white hat security professional",
    charter=(
        "You are a white hat security professional trying out this software "
        "on a fresh machine, the way a careful professional would before "
        "recommending it. Look for: files it writes with loose permissions, "
        "secrets shown on screen or written to logs, world-readable config, "
        "unsafe defaults, input it passes unescaped to a shell or a query, "
        "and install or update steps that fetch over plain http.\n"
        "White hat means: test only this software, only on this machine. "
        "Show that a problem exists; never exploit it further. Never scan, "
        "probe or connect to any other host, and never try to leave this "
        "machine. Network access is limited; a refused connection is "
        "expected, not a challenge.\n"
        "When you are done, write your notes: each problem you saw, with the "
        "exact command and the exact output that shows it."),
)

PERSONAS = {WHITE_HAT.key: WHITE_HAT}


def brief(persona: Persona, readme: str, helps: dict[str, str], installed: list[str]) -> str:
    """What the driller is told: the charter plus what a USER can see (the
    README, each entry point's --help, the installed paths). Not the source:
    an outsider's view is the one worth simulating (review, 2026-09-27)."""
    parts = [persona.charter, "", "## README", readme.strip() or "(none)"]
    for name in sorted(helps):
        parts += ["", f"## {name} --help", helps[name].strip()]
    parts += ["", "## Installed", *(sorted(installed) or ["(nothing listed)"])]
    return "\n".join(parts)


# --- refusals before any bench ----------------------------------------------

_HOST = re.compile(r"^([A-Za-z0-9-]+\.)*[A-Za-z0-9-]+(:[0-9]{1,5})?$")


def allow_problems(entry: str) -> str | None:
    """Why a brief's allowlist entry is refused, or None. Exact hostnames
    only, each with an optional port. No wildcard of any kind: `*.co.uk` or
    `*.github.io` admits hosts anyone can register, and no suffix list is
    complete enough to tell those from a safe one (Codex). No IP literal
    either: an address is how a driller would reach arf's internal range."""
    if "*" in entry:
        return f"{entry!r}: a wildcard; name each host the subject needs"
    if not _HOST.match(entry):
        return f"{entry!r}: not a host[:port]"
    try:
        ipaddress.ip_address(entry.split(":", 1)[0])
        return f"{entry!r}: an IP literal; name the host instead"
    except ValueError:
        pass
    return None


def policy_rules(ls_json) -> list[dict]:
    """The rules of `sbx policy ls --json` (every policy, every scope). JSON,
    not the `inspect` table: sbx 0.45 added METHOD/PATH/PROTOCOLS columns,
    and a fixed-column parse then read `-` as the status, so an active
    global `allow **` looked inactive and the host was NOT refused."""
    data = json.loads(ls_json) if isinstance(ls_json, str) else ls_json
    return list(data.get("rules") or [])


def _net(r: dict, decision: str, applies_to: str) -> bool:
    return (r.get("resource_type") == "network" and r.get("decision") == decision
            and r.get("status") == "active" and r.get("applies_to") == applies_to)


# Hosts whose GLOBAL policy check must come back denied: an ordinary public
# name, a public address, arf's gateway and the other bench-host. Checked
# with `sbx policy check network <canary> --json`.
CANARIES = ("gentar-canary.invalid:443", "1.1.1.1:443", "10.10.10.1:22", "10.10.10.52:22")


def host_problems(rules: list[dict], checks: list[dict]) -> list[str]:
    """Why this bench host cannot contain a driller.

    Deny-by-default is proven by asking sbx, not by finding a rule: on sbx
    0.45.1 `policy init deny-all` lists a `default-deny-all` rule only while
    no other network rule exists, and it vanishes from `policy ls --json`
    the moment any per-sandbox rule is added, with the default still denying
    (VM 151, 2026-09-28). So every canary's global `policy check` must say
    allowed=false, and no rule may allow anything for all sandboxes (a
    global allow cannot be narrowed per sandbox)."""
    out = []
    if not checks:
        out.append("no `sbx policy check` answers: deny-by-default is unproven")
    for c in checks:
        if c.get("allowed") is not False or c.get("context") != "global":
            out.append(f"the bench host's global policy allows {c.get('target', '?')} "
                       f"({c.get('reason', '?')}): a driller needs a deny-by-default host")
    for r in rules:
        if _net(r, "allow", "all"):
            out.append(f"the bench host globally allows {', '.join(r.get('resources') or [])} "
                       f"(rule {r.get('id')}): one sandbox cannot be narrowed below that")
    return out


def sandbox_problems(rules: list[dict], sandbox: str, allow: list[str]) -> list[str]:
    """Rules scoped to the driller's own sandbox that the brief did not ask
    for. sbx kits add per-sandbox rules on their own (`source: kit`); checked
    after the sandbox exists and before the driller types anything."""
    out = []
    for r in rules:
        if _net(r, "allow", f"sandbox:{sandbox}"):
            extra = [h for h in (r.get("resources") or []) if h not in allow]
            if extra:
                out.append(f"sandbox rule {r.get('id')} ({r.get('origin', '?')}) allows "
                           f"{', '.join(extra)}, which the brief does not name")
    return out


def start_refusals(env: dict, host_rules: list[dict], allow: list[str],
                   credentials: list[str], host_checks: list[dict]) -> list[str]:
    """Every reason this driller run must not start. Empty means go."""
    out = []
    for name in FORBIDDEN_ENV:
        if name in env:
            out.append(f"{name} is set: it sends BAML prompts and outputs to Boundary's "
                       f"hosted Studio. Unset it; drillers never use it")
    out += host_problems(host_rules, host_checks)
    for entry in allow:
        why = allow_problems(entry)
        if why:
            out.append(f"allowlist {why}")
    for name in sorted(n for n in set(credentials) if never_forward(n)):
        out.append(f"credential {name} can never reach a driller's bench")
    for key in ("GENTAR_DRILLER_MODEL_URL", "GENTAR_DRILLER_MODEL"):
        if not env.get(key):
            out.append(f"{key} is not set (the driller model route: 9router on tr0)")
    return out


def policy_argv(sandbox: str, allow: list[str]) -> list[str] | None:
    """The one rule a driller's sandbox gets on a deny-by-default host, or
    None for no network at all. The driller model is called by the
    coordinator, which types into the bench; the bench itself never needs a
    route to the model, so an empty allowlist is the normal case."""
    if not allow:
        return None
    return ["sbx", "policy", "allow", "network", "--sandbox", sandbox, ",".join(sorted(allow))]


# --- the audit after the run ------------------------------------------------

@dataclass
class Audit:
    denied: list[dict] = field(default_factory=list)     # tried; the wall held
    breaches: list[dict] = field(default_factory=list)   # got through: FAIL
    allowed: list[dict] = field(default_factory=list)    # on the allowlist


def host_allowed(host: str, allow: list[str]) -> bool:
    """`host` is sbx's `name:port`. An entry without a port allows any port.
    Exact names only; allow_problems refuses wildcards before any run."""
    name, _, port = host.rpartition(":") if ":" in host else (host, "", "")
    name = name.lower()
    for entry in allow:
        e_name, _, e_port = entry.lower().partition(":")
        if e_port and e_port != port:
            continue
        if "*" not in e_name and name == e_name:
            return True
    return False


def audit(log, sandbox: str, allow: list[str]) -> Audit:
    """Read `sbx policy log --json` for one sandbox. A blocked host is a
    finding; an allowed host that is NOT on the allowlist is a breach, which
    means the policy did not hold, so the run fails."""
    data = json.loads(log) if isinstance(log, str) else log
    out = Audit()
    for e in data.get("blocked_hosts") or []:
        if e.get("vm_name") == sandbox:
            out.denied.append(e)
    for e in data.get("allowed_hosts") or []:
        if e.get("vm_name") != sandbox:
            continue
        (out.allowed if host_allowed(str(e.get("host", "")), allow) else out.breaches).append(e)
    return out


def outside_changes(before: dict[str, set], after: dict[str, set], own: set) -> list[str]:
    """What changed on the bench host outside the driller's own sandbox:
    `before`/`after` map a kind ("sandboxes", "templates") to the names seen.
    Meaningful only on a host drillers do not share, which they require."""
    out = []
    for kind in sorted(set(before) | set(after)):
        b, a = before.get(kind, set()) - own, after.get(kind, set()) - own
        out += [f"{kind}: {n} appeared" for n in sorted(a - b)]
        out += [f"{kind}: {n} disappeared" for n in sorted(b - a)]
    return out


def verdict(result: Audit, outside: list[str], scrub=lambda s: s) -> tuple[int, list[str]]:
    """Hard facts only. 1 on any breach or outside change; else 0. Hosts are
    scrubbed: a driller can put a credential into a hostname it looks up."""
    reasons = [f"boundary breach: reached {scrub(str(e.get('host')))} "
               f"({e.get('proxy_type', '?')})" for e in result.breaches]
    reasons += [f"boundary breach: {scrub(c)}" for c in outside]
    return (1 if reasons else 0), reasons


# --- findings ---------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _ANSI.sub("", text)).strip()


def extract(hat: str, feedback: str, transcript: str, env=None, raw: str | None = None):
    """Feedback -> typed findings via BAML. `raw` parses a model answer
    offline (tests, replays); otherwise the model is called on our route."""
    env = os.environ if env is None else env
    for name in FORBIDDEN_ENV:
        if name in env:
            raise DrillerRefusal(f"{name} is set; refusing to call BAML")
    from gentar.baml_client import b
    if raw is not None:
        return list(b.parse.ExtractFindings(raw))
    # The model route only, passed explicitly: never the process
    # environment, which holds the arena's own keys.
    keys = ("GENTAR_DRILLER_MODEL_URL", "GENTAR_DRILLER_MODEL", "GENTAR_DRILLER_MODEL_KEY")
    client = b.with_options(env={k: env.get(k, "") for k in keys})
    return list(client.ExtractFindings(hat, feedback, transcript))


def supported(findings, transcript: str):
    """(kept, dropped): a finding stays only if its evidence appears in the
    transcript. A driller that claims what the screen never showed is
    speculating; the claim is dropped, not reported."""
    t = _norm(transcript)
    kept, dropped = [], []
    for f in findings:
        ev = _norm(getattr(f, "evidence", "") or "")
        (kept if ev and ev in t else dropped).append(f)
    return kept, dropped


# Numbers that differ between runs of the SAME finding: timestamps, clock
# times, month-day dates, and long ids (pids, inodes, byte counts). Other
# numbers carry meaning: "port 22" and "port 443" are two findings (Codex).
_VOLATILE = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?z?\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b"),
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) +\d{1,2}\b"),
    re.compile(r"\b\d{5,}\b"),
]


def _key(f) -> tuple[str, str]:
    cat = getattr(getattr(f, "category", None), "value", str(getattr(f, "category", "")))
    ev = _norm(getattr(f, "evidence", "")).lower()
    for rx in _VOLATILE:
        ev = rx.sub("#", ev)
    return cat, ev


@dataclass
class Cluster:
    category: str
    evidence: str
    runs: int
    example: object
    severity: str


def cluster(runs: list[list]) -> list[Cluster]:
    """The same finding across N runs. Frequency counts RUNS, not mentions:
    a run that reports one problem three times still counts once. Sorted by
    runs, then severity, then key, so the report reads the same each time."""
    seen: dict[tuple, dict] = {}
    for i, findings in enumerate(runs):
        for f in findings:
            k = _key(f)
            c = seen.setdefault(k, {"runs": set(), "example": f, "sev": "INFO"})
            c["runs"].add(i)
            sev = getattr(getattr(f, "severity", None), "value", str(getattr(f, "severity", "INFO")))
            if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(c["sev"], 0):
                c["sev"], c["example"] = sev, f
    out = [Cluster(k[0], k[1], len(v["runs"]), v["example"], v["sev"]) for k, v in seen.items()]
    out.sort(key=lambda c: (-c.runs, -SEVERITY_ORDER.get(c.severity, 0), c.category, c.evidence))
    return out


def render(clusters: list[Cluster], n_runs: int, audits: list[Audit], scrub=lambda s: s) -> str:
    """The report section. Findings are reported, never a verdict. Every
    quoted string goes through `scrub` (the run's Redactor): evidence is
    screen text, and a screen can hold a credential."""
    lines = [f"## Driller findings ({n_runs} runs)", ""]
    if not clusters:
        lines.append("No supported findings.")
    for c in clusters:
        f = c.example
        mark = "" if c.runs > 1 else " (single run)"
        lines += [f"- **{c.runs}/{n_runs}**{mark} {c.severity} {c.category}: {scrub(f.title)}",
                  f"  - evidence: `{scrub(_norm(f.evidence))}`",
                  f"  - reproduce: `{scrub(_norm(f.reproduce))}`"]
    # A blocked host is still driller-chosen text: `<token>.attacker.example`
    # is denied by the policy and would leak through the report (Codex).
    denied = sorted({scrub(str(e.get("host", "?"))) for a in audits for e in a.denied})
    lines += ["", "### Boundary", ""]
    lines.append("Blocked attempts (the wall held): " + (", ".join(denied) if denied else "none"))
    return "\n".join(lines)
