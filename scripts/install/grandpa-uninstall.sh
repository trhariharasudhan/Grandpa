#!/usr/bin/env bash
# grandpa-uninstall.sh — clean removal of Grandpa from $HOME.
#
# Removes:
#   ~/.grandpa/
#   ~/.local/bin/grandpa
#   ~/.local/bin/grandpa-uninstall
#
# Does NOT remove: ollama, uv, or the Rust toolchain.

set -euo pipefail

GRANDPA_HOME="${GRANDPA_HOME:-$HOME/.grandpa}"

if [[ -f "$GRANDPA_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$GRANDPA_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$GRANDPA_HOME" ]]; then
    rm -rf "$GRANDPA_HOME"
    echo "Removed $GRANDPA_HOME"
fi

for f in "$HOME/.local/bin/grandpa" "$HOME/.local/bin/grandpa-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

Grandpa removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
