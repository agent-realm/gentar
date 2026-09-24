#!/usr/bin/env bash
# Runs ON the arena host (bin/history deploy copies this directory there).
# Idempotent: generates any missing password, writes the users config with
# sha256 hashes only, (re)starts the store, applies the schema. No password
# is ever printed or passed on a command line.
set -euo pipefail
cd "$(dirname "$0")"
umask 077
mkdir -p secrets users.d
for u in admin writer reader; do
  [ -s "secrets/$u.pass" ] || python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "secrets/$u.pass"
done
chmod 600 secrets/*.pass
hash() { python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest())' "secrets/$1.pass"; }
cat > users.d/gentar.xml <<XML
<clickhouse>
  <users>
    <default remove="remove"/>
    <gentar_admin>
      <password_sha256_hex>$(hash admin)</password_sha256_hex>
      <networks><ip>::/0</ip></networks>
      <grants><query>GRANT ALL ON gentar_history.*</query></grants>
    </gentar_admin>
    <gentar_writer>
      <password_sha256_hex>$(hash writer)</password_sha256_hex>
      <networks><ip>::/0</ip></networks>
      <grants>
        <query>GRANT INSERT ON gentar_history.*</query>
        <query>GRANT SHOW COLUMNS ON gentar_history.*</query>
      </grants>
    </gentar_writer>
    <gentar_reader>
      <password_sha256_hex>$(hash reader)</password_sha256_hex>
      <networks><ip>::/0</ip></networks>
      <grants><query>GRANT SELECT ON gentar_history.*</query></grants>
    </gentar_reader>
  </users>
</clickhouse>
XML
chmod 644 users.d/gentar.xml       # the server reads it; hashes only
docker compose -f compose.yml up -d --wait
# schema over HTTP, credentials from a header FILE (not argv)
hdr=$(mktemp); trap 'rm -f "$hdr"' EXIT
{ echo "X-ClickHouse-User: gentar_admin"; printf 'X-ClickHouse-Key: %s\n' "$(cat secrets/admin.pass)"; } > "$hdr"
python3 - "$hdr" <<'PY'
import sys, urllib.request
hdrs = dict(l.rstrip("\n").split(": ", 1) for l in open(sys.argv[1]) if ": " in l)
for stmt in [s.strip() for s in open("schema.sql").read().split(";")]:
    body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if not body:
        continue
    req = urllib.request.Request("http://127.0.0.1:" + __import__("os").environ.get("GENTAR_HISTORY_PORT", "18199") + "/",
                                 data=body.encode(), headers=hdrs)
    urllib.request.urlopen(req, timeout=30).read()
print("schema applied")
PY
echo "gentar-history up on 127.0.0.1:${GENTAR_HISTORY_PORT:-18199} (docker network gentar-history)"
