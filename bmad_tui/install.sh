#!/usr/bin/env bash
# BMAD Dashboard TUI — installer
# Run from the repo root: tools/bmad_tui/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}  ▶${NC} $*"; }
ok()      { echo -e "${GREEN}  ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}  ⚠${NC} $*"; }
fail()    { echo -e "${RED}  ✖${NC} $*"; }
section() { echo -e "\n${BOLD}$*${NC}"; }

echo ""
echo -e "${BOLD}╔═══════════════════════════════╗${NC}"
echo -e "${BOLD}║   BMAD Dashboard TUI Setup    ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════╝${NC}"

# ── 1. Python ──────────────────────────────────────────────────────────────
section "1. Python environment"

VENV="$REPO_ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  warn ".venv not found — creating one at $VENV"
  python3 -m venv "$VENV"
  ok "Virtual environment created"
fi

PYTHON="$VENV/bin/python3"

if [[ ! -x "$PYTHON" ]]; then
  fail "Python not found at $PYTHON"
  exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11) ]]; then
  fail "Python 3.11+ required (found $PY_VERSION)"
  exit 1
fi
ok "Python $PY_VERSION"

# ── 2. pip bootstrap ───────────────────────────────────────────────────────
section "2. pip"

if ! "$PYTHON" -m pip --version &>/dev/null; then
  info "Bootstrapping pip…"
  "$PYTHON" -m ensurepip --upgrade
fi
ok "pip ready"

# ── 3. Python dependencies ─────────────────────────────────────────────────
section "3. Python dependencies"

info "Installing from tools/bmad_tui/requirements.txt…"
"$PYTHON" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
ok "textual + pyyaml installed"

# Also install pytest for the test suite
"$PYTHON" -m pip install -q pytest
ok "pytest installed"

# ── 4. expect ─────────────────────────────────────────────────────────────
section "4. expect (required for agent sessions)"

if command -v expect &>/dev/null; then
  ok "expect found: $(command -v expect)"
else
  warn "expect not found — install with: brew install expect"
  echo "       Agent sessions will not work until expect is installed."
fi

# ── 5. GitHub Copilot CLI ──────────────────────────────────────────────────
section "5. GitHub Copilot CLI"

if command -v copilot &>/dev/null; then
  ok "copilot found: $(command -v copilot)"
else
  warn "copilot CLI not found"
  echo "       Install: npm install -g @github/copilot-cli"
  echo "       See: https://docs.github.com/en/copilot/github-copilot-in-the-cli"
fi

# ── 6. Permissions ────────────────────────────────────────────────────────
section "6. File permissions"

chmod +x "$SCRIPT_DIR/session.expect"
ok "session.expect is executable"

LAUNCHER="$REPO_ROOT/tools/bmad-tui.sh"
if [[ -f "$LAUNCHER" ]]; then
  chmod +x "$LAUNCHER"
  ok "bmad-tui.sh is executable"
fi

# ── 7. Global install ─────────────────────────────────────────────────────
section "7. Global \`tui\` command"

echo ""
read -r -p "  Install \`tui\` as a global command (run from any git repo)? [y/N] " REPLY
echo ""

if [[ "${REPLY,,}" == "y" ]]; then
  GLOBAL_TUI="$HOME/.local/share/bmad-tui"
  BIN_DIR="$HOME/.local/bin"
  LAUNCHER_PATH="$BIN_DIR/tui"

  info "Copying TUI package to $GLOBAL_TUI …"
  mkdir -p "$GLOBAL_TUI"
  cp -r "$SCRIPT_DIR" "$GLOBAL_TUI/bmad_tui"

  info "Creating dedicated venv at $GLOBAL_TUI/.venv …"
  if [[ ! -x "$GLOBAL_TUI/.venv/bin/python3" ]]; then
    python3 -m venv "$GLOBAL_TUI/.venv"
  fi
  "$GLOBAL_TUI/.venv/bin/pip" install -q --upgrade textual pyyaml pyfiglet pytest

  info "Writing launcher to $LAUNCHER_PATH …"
  mkdir -p "$BIN_DIR"
  cat > "$LAUNCHER_PATH" << 'LAUNCHER_SCRIPT'
#!/usr/bin/env bash
# Global BMAD TUI launcher
# Finds nearest git repo going up, then runs the globally-installed TUI from there.

GLOBAL_TUI="$HOME/.local/share/bmad-tui"
PYTHON="$GLOBAL_TUI/.venv/bin/python3"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat << 'HELP'
tui — Global BMAD Dashboard launcher

USAGE
  tui            Launch the BMAD TUI for the nearest git repo
  tui --update   Refresh the global TUI install from the current repo's tools/bmad_tui
  tui --help     Show this message

HOW IT WORKS
  Running `tui` from any directory walks up the folder tree until it finds a
  git repository (.git), then launches the globally-installed TUI scoped to
  that repo root. No per-repo setup needed.

  The TUI itself is installed once at:
    ~/.local/share/bmad-tui/

  If you update tools/bmad_tui in a repo and want those changes reflected
  globally, run `tui --update` from inside that repo.

ERRORS
  "No git repository found" — you are not inside any git repo.
  "No tools/bmad_tui found"  — (--update only) no source to update from.
HELP
  exit 0
fi

if [[ "${1:-}" == "--update" ]]; then
  dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/tools/bmad_tui" ]]; then
      echo "🔄 Updating TUI from $dir/tools/bmad_tui …"
      cp -r "$dir/tools/bmad_tui" "$GLOBAL_TUI/bmad_tui"
      echo "✅ Updated."
      exit 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "❌ No tools/bmad_tui found in any parent directory."
  exit 1
fi

# Find nearest git root
dir="$PWD"
while [[ "$dir" != "/" ]]; do
  if [[ -d "$dir/.git" ]]; then
    cd "$dir"
    exec "$PYTHON" -c "
import sys; sys.path.insert(0, '$GLOBAL_TUI')
from bmad_tui.__main__ import main; main()
" "$@"
  fi
  dir="$(dirname "$dir")"
done

echo "❌ No git repository found in any parent directory."
exit 1
LAUNCHER_SCRIPT
  chmod +x "$LAUNCHER_PATH"
  ok "Launcher installed at $LAUNCHER_PATH"

  echo ""
  if echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    ok "$BIN_DIR is already in your PATH"
  else
    warn "$BIN_DIR is not in your PATH."
    echo ""
    echo "       Add this line to your ~/.zshrc or ~/.bashrc:"
    echo ""
    echo -e "         ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    echo ""
    echo "       Then restart your shell or run: source ~/.zshrc"
  fi
else
  info "Skipped. You can re-run this installer anytime to set it up."
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}✅ Setup complete.${NC}"
echo ""
echo -e "  Run the dashboard:  ${CYAN}tools/bmad-tui.sh${NC}"
echo -e "  Run the tests:      ${CYAN}tools/bmad-tui.sh --test${NC}"
if [[ "${REPLY,,}" == "y" ]]; then
  echo -e "  Global command:     ${CYAN}tui${NC}  (from any git repo)"
fi
echo ""
