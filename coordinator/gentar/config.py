"""Environment-driven configuration. Every knob is an env var with a
default matching today's setup (VM 9100 on arf) — same policy as
gauntlet's target.env."""

import os


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Config:
    def __init__(self) -> None:
        # Bench-host (an sbx host; default = the spike VM on arf).
        self.bench_host = _opt("GENTAR_BENCH_HOST", "10.10.10.200")
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
