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
# The builder's workspace is mounted into the builder sandbox, so it must be
# this account's own. On a host with several bench accounts a shared path in
# /tmp could be made first by another account, or be its symlink, and the
# template would be built from that account's directory. The default is per
# user, and a symlink or a directory another user owns is refused before any
# sbx call. It is made 0700, without -p, so a path someone else creates in
# between stops the build instead of being used.
WS=${GENTAR_TEMPLATE_WS:-${TMPDIR:-/tmp}/gentar-template-build-$(id -un)}

command -v sbx >/dev/null || { echo "sbx not installed"; exit 1; }

# shellcheck disable=SC3067  # -O: dash, bash and busybox sh all have it, as the kit's run.sh uses
if [ -L "$WS" ] || { [ -e "$WS" ] && [ ! -O "$WS" ]; }; then
  echo "builder workspace refused: $WS is a symlink or belongs to another user — remove it, or set GENTAR_TEMPLATE_WS" >&2
  exit 2
fi
rm -rf "$WS"
mkdir -p "$(dirname "$WS")"
(umask 077; mkdir "$WS")
trap 'rm -rf "$WS"' EXIT
sbx rm gentar-tpl-build --force >/dev/null 2>&1 || true

sbx create --name gentar-tpl-build shell "$WS" >/dev/null
sbx exec gentar-tpl-build sh -lc \
  "npm install -g @anthropic-ai/claude-code@$VERSION && claude --version"
sbx stop gentar-tpl-build >/dev/null
sbx template save gentar-tpl-build "$TAG" >/dev/null
sbx rm gentar-tpl-build --force >/dev/null

echo "template $TAG built with claude-code $VERSION:"
sbx template ls | grep "$TAG" || true
