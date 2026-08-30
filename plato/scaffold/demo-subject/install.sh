#!/bin/sh
# demo-subject's documented install: one directory + one state file.
# The scaffold's default install decision
# (cd "$WORKSPACE_DIR" && ./install.sh) runs this verbatim.
mkdir -p "$HOME/.demo-subject"
echo installed > "$HOME/.demo-subject/state.txt"
