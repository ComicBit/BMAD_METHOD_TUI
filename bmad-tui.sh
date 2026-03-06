#!/usr/bin/env bash
# Local convenience wrapper.
# Usage:
#   ./bmad-tui.sh
#   ./bmad-tui.sh --test

set -euo pipefail

LAUNCHER="$HOME/.local/bin/tui"

if [[ ! -x "$LAUNCHER" ]]; then
  echo "⚠  Global 'tui' launcher is not installed."
  echo "   Run the installer first: ./install.sh"
  exit 1
fi

if [[ "${1:-}" == "--test" ]]; then
  echo "🧪 Running BMAD TUI test suite…"
  python3 -m pytest bmad_tui/tests/ -v "${@:2}"
else
  exec "$LAUNCHER" "$@"
fi
