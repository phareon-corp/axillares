#!/usr/bin/env bash
# Instala o Axillares a partir deste repositório:
#   - comando `axil` em ~/.local/bin (via uv tool, Python 3.12, com a interface gráfica)
#   - atalho "Axillares" no menu de aplicativos, com ícone
# Opções:
#   --editavel   instala apontando para esta pasta (mudanças no código valem sem reinstalar)
#   --remover    desinstala e tira o atalho
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}"
ATALHO="$DADOS/applications/axillares.desktop"
ICONE="$DADOS/icons/hicolor/scalable/apps/axillares.svg"

if [[ "${1:-}" == "--remover" ]]; then
    command -v axil >/dev/null && axil atalho --remover >/dev/null || rm -f "$ATALHO" "$ICONE"
    uv tool uninstall axillares || true
    echo "Axillares removido."
    exit 0
fi

if ! command -v uv >/dev/null; then
    echo "✕ Este instalador usa o uv. Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "  e abra um terminal novo (ou rode: source ~/.local/bin/env)." >&2
    exit 1
fi

MODO=()
[[ "${1:-}" == "--editavel" ]] && MODO=(--editable)
uv tool install --force --python 3.12 "${MODO[@]}" "$RAIZ[gui]"
BIN="$(uv tool dir --bin)/axil"

"$BIN" atalho >/dev/null

echo "✓ Axillares instalado."
echo "  comando: $BIN"
echo "  atalho:  $ATALHO"
"$BIN" versao
case ":$PATH:" in
    *":$(dirname "$BIN"):"*) ;;
    *) echo "! $(dirname "$BIN") não está no PATH: rode 'uv tool update-shell' e abra um terminal novo." ;;
esac
if ! command -v podman >/dev/null && ! command -v docker >/dev/null; then
    echo "! Falta o Podman (ou o Docker), que roda as ferramentas de EDA. Fedora: sudo dnf install podman"
    echo "  · Ubuntu/Debian: sudo apt install podman · Arch: sudo pacman -S podman"
fi
echo
echo "Próximo passo: axil ambiente instalar   (baixa as ferramentas, uma vez só, ~4 GB)"
echo "Depois:        axil gui"
