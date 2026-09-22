"""Environment-driven configuration. Every knob is a GENTAR_* env var;
`.env.example` is the documented template (copy it to `.env`).

Defaults are GENERIC or absent — never one install's own machines. A
value that can only be the install's (which host benches run on, which
account to ssh in as, which cloud API key) has NO default: the
coordinator REFUSES the run (exit 2, before any bench exists) rather
than silently reaching for whatever address happened to be in the
source. BENCH_REQUIREMENTS is that contract — one entry per bench
tier, checked against the tier a run actually selects, so a tier
nobody uses never has to be configured."""

import os


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Env vars a bench tier cannot run without, as (var name, Config
# attribute). Only install-IDENTITY values belong here: a knob with a
# sane generic default (an ssh key path, a localhost server address, an
# image ref) is configuration, not identity, and stays out.
#
#   sbx      the Linux bench-host, and the account to ssh in as.
#   tart     the Mac running the tart CLI, and its account.
#   osb      nothing — the server address defaults to localhost, which
#            is generic and wrong for nobody in particular.
#   daytona  the account's API key. DaytonaBenchHost also refuses on
#            its own (for direct library use); coming through here is
#            what makes it an exit-2 verdict with a report.
BENCH_REQUIREMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "sbx": (("GENTAR_BENCH_HOST", "bench_host"),
            ("GENTAR_BENCH_USER", "bench_user")),
    "tart": (("GENTAR_TART_HOST", "tart_host"),
             ("GENTAR_TART_USER", "tart_user")),
    "osb": (),
    "daytona": (("GENTAR_DAYTONA_API_KEY", "daytona_api_key"),),
}


class Config:
    def __init__(self) -> None:
        # Bench-host: any Linux machine with `sbx` installed and logged
        # in once. NO default — gentar ships no bench-host of its own,
        # and a plausible-but-wrong address is worse than a refusal.
        self.bench_host = _opt("GENTAR_BENCH_HOST")
        self.bench_user = _opt("GENTAR_BENCH_USER")
        # Optional SSH jump host, e.g. "user@gateway". Empty = direct.
        self.bench_jump = _opt("GENTAR_BENCH_JUMP")
        self.bench_key = _opt("GENTAR_BENCH_KEY", "~/.ssh/id_ed25519")
        self.bench_known_hosts = _opt(
            "GENTAR_BENCH_KNOWN_HOSTS", "/tmp/gentar-known-hosts"
        )
        self.sbx_bin = _opt("GENTAR_SBX_BIN", "sbx")
        # Host-side dir that becomes each sandbox's workspace bind-mount.
        self.bench_workspace_root = _opt(
            "GENTAR_BENCH_WORKSPACE_ROOT", "/tmp/gentar-workspaces"
        )

        # Bench tier: "sbx" (default) or "tart" (macOS VMs). A scenario's
        # `bench = "tart"` overrides per-run.
        self.bench_kind = _opt("GENTAR_BENCH_KIND", "sbx")
        # tart tier: the Mac running the tart CLI (control plane) and the
        # guest user benches ssh in as. Guest ssh jumps through the tart
        # host — vmnet is only routed there.
        # No defaults either, same rule — but only enforced when a run
        # actually selects this tier (see BENCH_REQUIREMENTS).
        self.tart_host = _opt("GENTAR_TART_HOST")
        self.tart_user = _opt("GENTAR_TART_USER")
        self.tart_vm_user = _opt("GENTAR_TART_VM_USER", "admin")
        # Absolute path: non-interactive ssh shells don't source PATH
        # wrappers, so a bare "tart" is not found over ssh.
        self.tart_bin = _opt("GENTAR_TART_BIN", "/opt/homebrew/bin/tart")

        # osb tier: the opensandbox-server (docker runtime) driving the
        # benches. Runs wherever the sandbox containers should live; the
        # coordinator reaches it over HTTP. A scenario's `bench = "osb"`
        # overrides per-run. Templates are image refs on that server's
        # docker daemon; api_key only if the server enforces one.
        self.osb_server = _opt("GENTAR_OSB_SERVER", "http://127.0.0.1:8080")
        self.osb_api_key = _opt("GENTAR_OSB_API_KEY")
        self.osb_template = _opt("GENTAR_OSB_TEMPLATE", "python:3.12-slim")
        # Route ALL sandbox traffic (exec/files/pty) through the server's
        # execd proxy instead of per-sandbox host ports. Needed when the
        # coordinator can't reach sandbox ports directly (coordinator
        # container + sandboxes on the server's docker host — the server
        # hands out its own host-relative endpoints either way).
        self.osb_server_proxy = _opt("GENTAR_OSB_SERVER_PROXY", "") == "1"

        # daytona tier: Daytona cloud sandboxes (daytona.io). Lifecycle via
        # the SDK (api key required); exec/pty via ssh with a per-sandbox
        # expiring token as username against the fixed ssh gateway.
        # Templates are public image refs with a tag or digest (no
        # `latest`). A scenario's `bench = "daytona"` overrides per-run.
        self.daytona_api_key = _opt("GENTAR_DAYTONA_API_KEY")
        self.daytona_image = _opt("GENTAR_DAYTONA_IMAGE", "python:3.12-slim")
        self.daytona_ssh_host = _opt("GENTAR_DAYTONA_SSH_HOST",
                                     "ssh.app.daytona.io")

        # Telemetry. Best-effort: telemetry never fails a test.
        self.clickhouse_url = _opt("GENTAR_CLICKHOUSE_URL", "http://clickhouse:8123")
        self.clickhouse_user = _opt("GENTAR_CLICKHOUSE_USER", "gentar")
        self.clickhouse_password = _opt("GENTAR_CLICKHOUSE_PASSWORD", "gentar")
        self.clickhouse_db = _opt("GENTAR_CLICKHOUSE_DB", "gentar")

        # Sandbox name prefix; run id is appended by the coordinator.
        self.name_prefix = _opt("GENTAR_NAME_PREFIX", "gentar")

        # Subjects root: mounted read-only into the coordinator container
        # (compose volume). A scenario's `subject` names a dir under it.
        self.subjects_root = _opt("GENTAR_SUBJECTS_ROOT", "/subjects")
        # TOML scenario dirs (baked /app/scenarios first, extras appended).
        self.scenarios_dirs = ["/app/scenarios"]
        extra = _opt("GENTAR_SCENARIOS_DIR")
        if extra:
            self.scenarios_dirs.append(extra)

        # Flake quarantine: comma-separated scenario names. A quarantined
        # scenario is SKIPPED (exit 0, span skip), never failed — a known
        # flake must not paint the suite red while its owner investigates.
        self.quarantine = {
            s.strip() for s in _opt("GENTAR_QUARANTINE").split(",") if s.strip()
        }

        # Budget guard. Scenarios declare [budget] tokens; the coordinator
        # refuses (exit 2) a run whose declared spend would exceed the cap
        # given what past runs already burned (accumulated from spans —
        # telemetry-down means spend reads as 0, same best-effort policy).
        # Caps are in "spend units" (tokens today; dollars if you prefer).
        self.budget_cap = int(_opt("GENTAR_BUDGET_CAP", "0") or 0)  # 0 = off

        # Engine provenance: the coordinator image has no .git — the sha
        # is injected at deploy time (CI sets it; local runs say "dev").
        self.engine_sha = _opt("GENTAR_ENGINE_SHA", "dev")
        self.engine_dirty = _opt("GENTAR_ENGINE_DIRTY", "")

        # OTLP endpoint for agent self-report relay (otelcol, compose
        # network). Benches have no inbound route to the arena, so agents
        # drop OTLP-JSON at $WORKSPACE_DIR/gentar-otlp.json and the
        # coordinator relays it here.
        self.otlp_endpoint = _opt("GENTAR_OTLP_ENDPOINT", "http://otelcol:4318")

        # Run reports: every run writes a markdown report here (bind
        # ./out:/out in compose). Empty string disables reporting.
        self.report_dir = _opt("GENTAR_REPORT_DIR", "/out")

    # -- install-identity guard --------------------------------------

    def missing_bench_env(self, kind: str = "") -> list[str]:
        """Env var names the selected bench tier needs and does not
        have, in declaration order. Empty = the tier is configured.

        Checked per RUN, not at load: a scenario picks its tier, and an
        install that only ever uses sbx must not have to configure tart
        for its config to load. An unknown kind needs nothing here —
        make_bench rejects it by name, which is the clearer message."""
        kind = kind or self.bench_kind
        return [var for var, attr in BENCH_REQUIREMENTS.get(kind, ())
                if not getattr(self, attr, "").strip()]
