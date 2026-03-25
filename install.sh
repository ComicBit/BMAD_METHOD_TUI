#!/usr/bin/env bash
# BMAD Dashboard TUI installer
# Run from the repo root or directly:
#   ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
INSTALL_ROOT="$HOME/.local/share/bmad-tui"
BIN_DIR="$HOME/.local/bin"
LAUNCHER_PATH="$BIN_DIR/tui"
PYTHON_BIN="${PYTHON:-python3}"

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

detect_shell_rc() {
  local shell_name rc
  shell_name="$(basename "${SHELL:-}")"
  case "$shell_name" in
    zsh) rc="$HOME/.zshrc" ;;
    bash) rc="$HOME/.bashrc" ;;
    *) rc="$HOME/.profile" ;;
  esac
  printf '%s\n' "$rc"
}

ensure_path_in_shell() {
  local rc_file path_line
  rc_file="$(detect_shell_rc)"
  path_line='export PATH="$HOME/.local/bin:$PATH"'

  mkdir -p "$(dirname "$rc_file")"
  touch "$rc_file"

  if grep -Fqx "$path_line" "$rc_file"; then
    ok "$BIN_DIR already exported in $(basename "$rc_file")"
    return
  fi

  printf '\n%s\n' "$path_line" >> "$rc_file"
  ok "Added $BIN_DIR to $(basename "$rc_file")"
}

echo ""
echo -e "${BOLD}╔═══════════════════════════════╗${NC}"
echo -e "${BOLD}║   BMAD Dashboard TUI Setup    ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════╝${NC}"

section "1. Python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  fail "Python 3.11+ is required but '$PYTHON_BIN' was not found."
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" --version 2>&1 | awk '{print $2}')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11) ]]; then
  fail "Python 3.11+ required (found $PY_VERSION)"
  exit 1
fi

ok "Python $PY_VERSION"

section "2. Global install location"

info "Installing to $INSTALL_ROOT"
mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
rm -rf "$INSTALL_ROOT/bmad_tui"
cp -R "$REPO_ROOT/bmad_tui" "$INSTALL_ROOT/bmad_tui"
chmod +x "$INSTALL_ROOT/bmad_tui/session.expect"
ok "Copied package files"

section "3. Virtual environment"

if [[ ! -x "$INSTALL_ROOT/.venv/bin/python3" ]]; then
  info "Creating virtual environment"
  "$PYTHON_BIN" -m venv --system-site-packages "$INSTALL_ROOT/.venv"
fi

VENV_PYTHON="$INSTALL_ROOT/.venv/bin/python3"
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  info "Bootstrapping pip"
  "$VENV_PYTHON" -m ensurepip --upgrade
fi

if "$VENV_PYTHON" -c "import textual, yaml, pyfiglet" >/dev/null 2>&1; then
  ok "Python dependencies already available"
else
  info "Installing Python dependencies"
  "$VENV_PYTHON" -m pip install -q -r "$INSTALL_ROOT/bmad_tui/requirements.txt"
  ok "Dependencies installed"
fi

section "4. CLI prerequisites"

if command -v expect >/dev/null 2>&1; then
  ok "expect found: $(command -v expect)"
else
  warn "expect not found"
  echo "     Install it with: brew install expect"
fi

if command -v copilot >/dev/null 2>&1; then
  ok "copilot found: $(command -v copilot)"
elif command -v claude >/dev/null 2>&1; then
  ok "claude found: $(command -v claude)"
else
  warn "Neither copilot nor claude CLI was found"
  echo "     Install one of them before launching agent sessions."
fi

section "5. Global 'tui' command"

cat > "$LAUNCHER_PATH" <<'LAUNCHER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/bmad-tui"
PYTHON="$INSTALL_ROOT/.venv/bin/python3"

find_git_root() {
  local dir
  dir="$(pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.git" || -f "$dir/.git" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

is_bmad_repo() {
  local root="$1"
  [[ -d "$root/_bmad" || -d "$root/_bmad-output" ]]
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'HELP'
tui — BMAD Dashboard launcher

USAGE
  tui        Launch the BMAD Dashboard for the current BMAD git repo
  tui --help Show this help

RULES
  - You must run this inside a git repository, or inside a subdirectory of one.
  - That repository must contain BMAD folders: `_bmad` or `_bmad-output`.

INSTALL LOCATION
  ~/.local/share/bmad-tui
HELP
  exit 0
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "❌ BMAD Dashboard TUI is not installed correctly."
  echo "   Re-run: ./install.sh"
  exit 1
fi

if ! ROOT="$(find_git_root)"; then
  echo "❌ No git repository found in the current directory or its parents."
  echo "   Run 'tui' from inside a BMAD project repository."
  exit 1
fi

if ! is_bmad_repo "$ROOT"; then
  echo "❌ Found git repository at:"
  echo "   $ROOT"
  echo "   but it does not look like a BMAD repo."
  echo "   Expected at least one of: _bmad, _bmad-output"
  exit 1
fi

cd "$ROOT"
export PYTHONPATH="$INSTALL_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m bmad_tui "$@"
LAUNCHER_SCRIPT

chmod +x "$LAUNCHER_PATH"
ok "Installed launcher at $LAUNCHER_PATH"

section "6. Shell PATH"

ensure_path_in_shell

echo ""
echo -e "${GREEN}${BOLD}✅ Setup complete.${NC}"
echo ""
echo "Next steps:"
echo "  1. Open a new terminal, or run: source \"$(detect_shell_rc)\""
echo "  2. Move into a git repo that contains _bmad or _bmad-output"
echo "  3. Run: tui"
