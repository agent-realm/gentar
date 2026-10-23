#!/bin/sh
# bench-template/build.sh — deterministic bench template builder.
# Runs ON the bench-host (any host with `sbx` logged in). Creates a
# builder sandbox, installs the pinned agent CLI, snapshots it as a
# template, cleans up. The pin lives in VERSION (single source); the
# bench-template-verify scenario asserts the same version from inside
# benches created from the template.
#
#   ssh bench-host sh -s -- "$(cat bench-template/VERSION)" < bench-template/build.sh
#
# Piped like that, the script cannot read VERSION from the bench-host
# (it is not there), so the pin travels as the first argument. Run from a
# copy of this directory, `sh build.sh` reads ./VERSION instead.
#
# A template save blocks the sbx daemon for the whole host while it runs:
# announce a window with no arena run in flight first.
set -e

TAG=gentar-bench-v1
if [ -n "${1:-}" ]; then
  VERSION=$1
elif [ -f VERSION ]; then
  VERSION=$(cat VERSION)
else
  echo "no agent version: pass it as the first argument (sh -s -- \"\$(cat bench-template/VERSION)\")," >&2
  echo "or run from a copy of bench-template/ that holds VERSION" >&2
  exit 2
fi
case "$VERSION" in
  ''|*[!0-9A-Za-z.-]*) echo "bad agent version: $VERSION" >&2; exit 2 ;;
esac
WS=${GENTAR_TEMPLATE_WS:-/tmp/gentar-template-build}   # the builder's workspace

command -v sbx >/dev/null || { echo "sbx not installed"; exit 1; }

rm -rf "$WS" && mkdir -p "$WS"
sbx rm gentar-tpl-build --force >/dev/null 2>&1 || true

sbx create --name gentar-tpl-build shell "$WS" >/dev/null
sbx exec gentar-tpl-build sh -lc \
  "npm install -g @anthropic-ai/claude-code@$VERSION && claude --version"
sbx stop gentar-tpl-build >/dev/null
sbx template save gentar-tpl-build "$TAG" >/dev/null
sbx rm gentar-tpl-build --force >/dev/null
rm -rf "$WS"

echo "template $TAG built with claude-code $VERSION:"
sbx template ls | grep "$TAG" || true
