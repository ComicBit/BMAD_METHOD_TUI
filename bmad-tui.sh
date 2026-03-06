#!/usr/bin/env bash
# BMAD Dashboard TUI — launcher
# Usage:
#   tools/bmad-tui.sh          # launch the dashboard
#   tools/bmad-tui.sh --test   # run the test suite

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python3"

if [[ ! -x "$PYTHON" ]]; then
  echo "⚠  Virtual environment not found at $VENV"
  echo "   Run the installer first:  tools/bmad_tui/install.sh"
  exit 1
fi

if ! "$PYTHON" -c "import textual, yaml" 2>/dev/null; then
  echo "⚠  Dependencies not installed."
  echo "   Run the installer first:  tools/bmad_tui/install.sh"
  exit 1
fi

cd "$REPO_ROOT"

if [[ "${1:-}" == "--test" ]]; then
  echo "🧪 Running BMAD TUI test suite…"
  "$PYTHON" -m pytest tools/bmad_tui/tests/ -v "$@"
else
  "$PYTHON" -m tools.bmad_tui "$@"
fi
