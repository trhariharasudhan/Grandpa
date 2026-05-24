#!/usr/bin/env bash
# grandpa-wrapper.sh — symlinked to ~/.local/bin/grandpa.
# Activates the managed venv and execs the real grandpa CLI.

GRANDPA_HOME="${GRANDPA_HOME:-$HOME/.grandpa}"
VENV="$GRANDPA_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "grandpa: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://grandpa.ai/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/grandpa" "$@"
