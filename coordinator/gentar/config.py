"""Environment-driven configuration. Every knob is an env var with a
default matching today's setup (VM 142, gentar-bench-host on arf) — same
policy as gauntlet's target.env."""

import os


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Config:
    def __init__(self) -> None:
        # Bench-host (an sbx host; default = VM 142, gentar-bench-host).
        self.bench_host = _opt("GENTAR_BENCH_HOST", "10.10.10.52")
        self.bench_user = _opt("GENTAR_BENCH_USER", "polat")
        # Optional SSH jump host, e.g. "pilot@arf". Empty = direct.
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
