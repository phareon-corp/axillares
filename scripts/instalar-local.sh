#!/usr/bin/env bash
# Instala o Axillares para uso local, a partir deste checkout, em modo editável:
# alterações no código valem na próxima execução, sem reinstalar.
#   - comando `axil` em ~/.local/bin (via uv tool, Python 3.12, com a GUI)
#   - atalho "Axillares" no menu de aplicativos, com ícone
# Desinstalar: scripts/instalar-local.sh --remover
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}"
ATALHO="$DADOS/applications/axillares.desktop"
ICONE="$DADOS/icons/hicolor/scalable/apps/axillares.svg"

if [[ "${1:-}" == "--remover" ]]; then
    uv tool uninstall axillares || true
    rm -f "$ATALHO" "$ICONE"
    update-desktop-database "$DADOS/applications" 2>/dev/null || true
    echo "Axillares removido."
    exit 0
fi

if ! command -v uv >/dev/null; then
    echo "✕ Este instalador usa o uv. Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

uv tool install --force --python 3.12 --editable "$RAIZ[gui]"
BIN="$(uv tool dir --bin)/axil"

install -Dm644 "$RAIZ/src/axillares/gui/icones/axillares.svg" "$ICONE"
install -d "$(dirname "$ATALHO")"
cat > "$ATALHO" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Axillares
GenericName=Projeto de circuitos integrados
Comment=Do Verilog ao GDSII com ferramentas abertas
Exec=$BIN gui
Icon=axillares
Terminal=false
Categories=Development;Electronics;Engineering;
Keywords=EDA;Verilog;ASIC;FPGA;GDSII;chip;
StartupWMClass=axillares
StartupNotify=true
DESKTOP
update-desktop-database "$DADOS/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$DADOS/icons/hicolor" 2>/dev/null || true

echo "✓ Axillares instalado."
echo "  comando: $BIN"
echo "  atalho:  $ATALHO"
"$BIN" versao
