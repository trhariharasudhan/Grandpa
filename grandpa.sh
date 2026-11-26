#!/usr/bin/env sh
# Grandpa launcher for Linux and macOS, the twin of grandpa.cmd on Windows.
# Runs Grandpa from this folder's project environment; the current folder is kept.
# To call it as "grandpa" from anywhere, run scripts/install_launcher.sh once.
set -e
if ! command -v uv >/dev/null 2>&1; then
  echo "Grandpa needs uv. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 127
fi
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
GRANDPA_LAUNCHER=${GRANDPA_LAUNCHER:-grandpa.sh}
export GRANDPA_LAUNCHER
exec uv run --project "$here" python -m grandpa "$@"
