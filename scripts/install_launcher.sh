#!/usr/bin/env sh
# Put a "grandpa" command on your PATH (Linux and macOS).
#
# Writes a small shim to ~/.local/bin/grandpa that runs
#   uv run --project <this repo> python -m grandpa <args>
# Run it again any time; it only rewrites its own shim.
#
#   sh scripts/install_launcher.sh             install
#   sh scripts/install_launcher.sh --uninstall remove the shim
#
# BIN_DIR=/some/dir sh scripts/install_launcher.sh puts the shim elsewhere.
set -e
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
bin_dir=${BIN_DIR:-"$HOME/.local/bin"}
shim="$bin_dir/grandpa"

if [ "${1:-}" = "--uninstall" ]; then
  if [ -f "$shim" ] && grep -q "Grandpa launcher shim" "$shim"; then
    rm -f "$shim"
    echo "Removed $shim"
  else
    echo "No Grandpa shim at $shim"
  fi
  exit 0
fi

if [ -e "$shim" ] && ! grep -q "Grandpa launcher shim" "$shim"; then
  echo "$shim exists and is not Grandpa's shim; leaving it alone." >&2
  exit 1
fi

mkdir -p "$bin_dir"
cat > "$shim" <<SHIM
#!/usr/bin/env sh
# Grandpa launcher shim (written by scripts/install_launcher.sh)
GRANDPA_LAUNCHER=shim exec "$repo/grandpa.sh" "\$@"
SHIM
chmod +x "$shim"
echo "Installed $shim -> $repo"

case ":$PATH:" in
  *":$bin_dir:"*) echo "Type: grandpa" ;;
  *)
    echo "$bin_dir is not on your PATH yet. Add this line to ~/.bashrc (or ~/.zshrc):"
    echo "  export PATH=\"$bin_dir:\$PATH\""
    ;;
esac
