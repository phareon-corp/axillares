#!/usr/bin/env bash
# Instala o Axillares a partir deste repositório, com tudo de que ele precisa:
#   1. pacotes do sistema que faltarem (Podman, bibliotecas do Qt 6, curl), pelo
#      gerenciador da distribuição — dnf, apt, pacman ou zypper (pede a senha só aqui,
#      e só se faltar algo);
#   2. o uv, se não houver (instalador oficial, no perfil do usuário);
#   3. o comando `axil` em ~/.local/bin (uv tool, Python 3.12 baixado pelo uv, com a GUI);
#   4. o atalho "Axillares" no menu de aplicativos, com ícone;
#   5. as ferramentas de EDA (imagem de contêiner fixada por digest, ~4 GB, uma vez só)
#      e o elkjs, e confere cada ferramenta.
# Rodar de novo é seguro: o que já está pronto é pulado.
#
# Opções:
#   --editavel     instala apontando para esta pasta (mudanças no código valem sem reinstalar)
#   --sem-sistema  não mexe nos pacotes do sistema (sem sudo)
#   --sem-ambiente não baixa a imagem de ferramentas agora (dá para baixar depois pela tela
#                  Abertura ou com `axil ambiente instalar`)
#   --remover      desinstala e tira o atalho
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DADOS="${XDG_DATA_HOME:-$HOME/.local/share}"
ATALHO="$DADOS/applications/axillares.desktop"
ICONE="$DADOS/icons/hicolor/scalable/apps/axillares.svg"

EDITAVEL=0
SEM_SISTEMA=0
SEM_AMBIENTE=0
for arg in "$@"; do
    case "$arg" in
        --editavel) EDITAVEL=1 ;;
        --sem-sistema) SEM_SISTEMA=1 ;;
        --sem-ambiente) SEM_AMBIENTE=1 ;;
        --remover)
            command -v axil >/dev/null && axil atalho --remover >/dev/null || rm -f "$ATALHO" "$ICONE"
            uv tool uninstall axillares || true
            echo "Axillares removido."
            echo "A imagem de ferramentas continua no Podman; para liberar o espaço:"
            echo "  podman rmi docker.io/hpretl/iic-osic-tools"
            exit 0 ;;
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "opção desconhecida: $arg (veja --help)" >&2; exit 2 ;;
    esac
done

etapa() { printf '\n\033[1m● %s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }
aviso() { printf '  \033[33m!\033[0m %s\n' "$*"; }
falha() { printf '\033[31m✕ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. sistema ────────────────────────────────────────────────────────────────
# O Qt 6 carrega estas bibliotecas para abrir a janela no X11/XWayland; a que mais
# falta em instalação nova é a xcb-cursor, e sem ela a janela não abre.
falta_algo() {
    local c lib
    for c in curl; do command -v "$c" >/dev/null || { info "falta: $c"; return 0; }; done
    command -v podman >/dev/null || command -v docker >/dev/null || { info "falta: podman"; return 0; }
    for lib in libxcb-cursor.so.0 libxkbcommon-x11.so.0 libxcb-icccm.so.4 libxcb-keysyms.so.1 \
               libEGL.so.1 libGL.so.1 libfontconfig.so.1 libdbus-1.so.3 libglib-2.0.so.0; do
        ldconfig -p 2>/dev/null | grep -q "$lib" || { info "falta: $lib"; return 0; }
    done
    return 1
}

apt_escolher() {   # "a|b": o primeiro nome que existir no repositório
    local grupo alt
    for grupo in "$@"; do
        for alt in ${grupo//|/ }; do
            apt-cache show --no-all-versions "$alt" >/dev/null 2>&1 && { echo "$alt"; break; }
        done
    done
}

instalar_sistema() {
    local SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null || falha "faltam pacotes do sistema e não há sudo; instale-os como root e rode com --sem-sistema."
        SUDO="sudo"
        info "os pacotes do sistema vão pedir sua senha (sudo)"
    fi
    if command -v dnf >/dev/null; then
        $SUDO dnf install -y curl podman xcb-util-cursor xcb-util-wm xcb-util-image \
            xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 mesa-libEGL mesa-libGL \
            libglvnd-opengl fontconfig dbus-libs glib2
    elif command -v apt-get >/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        $SUDO apt-get update -q
        # shellcheck disable=SC2046
        $SUDO apt-get install -y -q $(apt_escolher curl ca-certificates podman uidmap \
            libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
            libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-randr0 libx11-xcb1 \
            libegl1 "libgl1|libgl1-mesa-glx" libopengl0 libfontconfig1 libdbus-1-3 \
            "libglib2.0-0t64|libglib2.0-0")
    elif command -v pacman >/dev/null; then
        $SUDO pacman -S --needed --noconfirm curl podman xcb-util-cursor xcb-util-wm \
            xcb-util-image xcb-util-keysyms xcb-util-renderutil libxkbcommon-x11 libglvnd \
            fontconfig dbus glib2
    elif command -v zypper >/dev/null; then
        $SUDO zypper --non-interactive install curl podman libxcb-cursor0 libxcb-icccm4 \
            libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0 libEGL1 \
            libGL1 libOpenGL0 fontconfig libdbus-1-3 libglib-2_0-0
    else
        falha "não reconheci o gerenciador de pacotes. Instale à mão o Podman, o curl e as bibliotecas xcb do Qt 6; depois rode com --sem-sistema."
    fi
}

etapa "1/5  dependências do sistema"
if falta_algo; then
    if [ "$SEM_SISTEMA" -eq 1 ]; then
        aviso "faltam pacotes, mas --sem-sistema foi pedido; seguindo assim mesmo"
    else
        instalar_sistema
    fi
else
    info "tudo presente"
fi

# ── 2. uv ─────────────────────────────────────────────────────────────────────
etapa "2/5  uv (instala o Python e o Axillares)"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    info "baixando o uv (instalador oficial da Astral, em ~/.local/bin)"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null \
        || falha "não consegui instalar o uv (sem internet?)"
    command -v uv >/dev/null || falha "o uv foi instalado mas não está em ~/.local/bin"
fi
info "$(uv --version)"

# ── 3. Axillares ──────────────────────────────────────────────────────────────
etapa "3/5  Axillares"
MODO=()
[ "$EDITAVEL" -eq 1 ] && MODO=(--editable)
uv tool install --quiet --force --python 3.12 "${MODO[@]}" "$RAIZ[gui]"
BIN="$(uv tool dir --bin)/axil"
info "comando: $BIN ($("$BIN" versao 2>/dev/null | head -1))"

# ── 4. atalho ─────────────────────────────────────────────────────────────────
etapa "4/5  atalho no menu"
"$BIN" atalho >/dev/null
info "atalho: $ATALHO"

# ── 5. ferramentas de EDA ─────────────────────────────────────────────────────
etapa "5/5  ferramentas de EDA"
if [ "$SEM_AMBIENTE" -eq 1 ]; then
    info "pulado (--sem-ambiente). Depois: axil ambiente instalar — ou pela tela Abertura."
elif ! command -v podman >/dev/null && ! command -v docker >/dev/null; then
    aviso "sem Podman nem Docker, as ferramentas não têm onde rodar; instale o Podman e rode de novo."
else
    "$BIN" ambiente instalar || falha "o download das ferramentas não terminou; rode de novo para continuar de onde parou."
    "$BIN" ambiente verificar || aviso "alguma ferramenta não passou na conferência — veja acima."
fi

case ":$(printenv PATH | sed "s|$HOME/.local/bin:||"):" in
    *":$(dirname "$BIN"):"*) ;;
    *) aviso "$(dirname "$BIN") não está no PATH do seu terminal: rode 'uv tool update-shell' e abra um terminal novo (o atalho do menu funciona assim mesmo)." ;;
esac
printf '\n\033[32m✓ Axillares instalado.\033[0m Abra pelo menu ("Axillares") ou rode: axil gui\n'
