#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
BIN_DIR="$HOME/.local/bin"
SHIM="$BIN_DIR/nubli"

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
CYAN='\033[36m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'
SHOW_PET=1

for arg in "$@"; do
  case "$arg" in
    --no-pet|--plain)
      SHOW_PET=0
      ;;
  esac
done

if [[ "${NUBLI_NO_PET:-}" == "1" ]]; then
  SHOW_PET=0
fi

banner() {
  printf "%b" "$CYAN"
  cat <<'ART'
 _   _       _     _ _
| \ | |_   _| |__ | (_)
|  \| | | | | '_ \| | |
| |\  | |_| | |_) | | |
|_| \_|\__,_|_.__/|_|_|

ART
  if [[ "$SHOW_PET" == "1" ]]; then
    cat <<'PET'
        /\_/\\
   ____/ o o \
 /~____  =ø= /
(______)__m_m)
   Nubli cat says: redact before you chat.

PET
  fi
  printf "%b\n" "$RESET${BOLD}local-first anonymizer — private docs stay local${RESET}"
  printf "%b\n\n" "${DIM}PDF • images • DOCX • XLSX • CSV • Markdown • text${RESET}"
}

step() { printf "%b\n" "${GREEN}✓${RESET} $1"; }
warn() { printf "%b\n" "${YELLOW}!${RESET} $1"; }
fail() { printf "%b\n" "${RED}x${RESET} $1" >&2; exit 1; }

need_python() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
  else
    fail "Python 3.10+ is required. Install Python first."
  fi
  "$PYTHON" - <<'PY' || fail "Python 3.10+ is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" "$@"
  else
    "$VENV/bin/python" -m pip install "$@"
  fi
}

install_core() {
  need_python
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  pip_install -e "$ROOT"
  mkdir -p "$BIN_DIR"
  cat > "$SHIM" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$ROOT/nubli.py" "\$@"
EOF
  chmod +x "$SHIM"
  step "Installed nubli shim at $SHIM"
}

install_full() {
  install_core
  step "Installing local document extras..."
  pip_install -e "$ROOT[all]"
  step "Python extras installed"
}

install_tesseract_hint() {
  if command -v tesseract >/dev/null 2>&1; then
    step "Tesseract already installed"
    return
  fi
  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    warn "OCR needs Tesseract. Installing with Homebrew..."
    brew install tesseract tesseract-lang
    step "Tesseract installed"
  else
    warn "Install Tesseract manually for OCR: https://tesseract-ocr.github.io/"
  fi
}

show_menu() {
  banner
  cat <<MENU
Choose install mode:

  1) Core      - fast CLI for text/CSV/Markdown
  2) Full      - PDF/images/DOCX/XLSX extras
  3) OCR too   - Full + local Tesseract OCR helper
  4) Uninstall shim only
  5) Exit

Tip: hide the mascot with NUBLI_NO_PET=1 ./install.sh or ./install.sh --no-pet

MENU
  printf "Select [1-5]: "
}

uninstall_shim() {
  rm -f "$SHIM"
  step "Removed $SHIM"
}

main() {
  while true; do
    show_menu
    read -r choice
    case "$choice" in
      1) install_core; break ;;
      2) install_full; break ;;
      3) install_full; install_tesseract_hint; break ;;
      4) uninstall_shim; break ;;
      5) exit 0 ;;
      *) warn "Pick 1, 2, 3, 4 or 5" ;;
    esac
  done

  printf "\n%b\n" "${GREEN}Done.${RESET} Try:"
  printf "  %b\n" "$SHIM --help"
  printf "  %b\n" "$SHIM"
  if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in PATH. Add this to your shell profile:"
    printf "  export PATH=\"%s:\$PATH\"\n" "$BIN_DIR"
  fi
}

main "$@"
