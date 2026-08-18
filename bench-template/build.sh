#!/bin/sh
# bench-template/build.sh — deterministic bench template builder.
# Runs ON the bench-host (any host with `sbx` logged in). Creates a
# builder sandbox, installs the pinned agent CLI, snapshots it as a
# template, cleans up. The pin lives in VERSION (single source); the
# bench-template-verify scenario asserts the same version from inside
# benches created from the template.
#
#   ssh bench-host 'sh -s' < bench-template/build.sh
set -e

TAG=gentar-bench-v1
VERSION=$(cat VERSION)
WS=/tmp/gentar-template-build

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
