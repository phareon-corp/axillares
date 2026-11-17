"""Atalho no menu de aplicativos (padrão freedesktop: GNOME, KDE, XFCE, Cinnamon…).

Funciona para qualquer forma de instalação (uv tool, pipx, pip, script): o atalho aponta para o
executável `axil` que está rodando agora. Fica em ~/.local/share/applications, com o ícone em
~/.local/share/icons — nada fora da pasta do usuário, sem sudo.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from axillares.ambiente.executor import Executor, ExecutorReal

NOME = "axillares"


@dataclass(frozen=True)
class Atalho:
    desktop: Path
    icone: Path
    executavel: Path


def _dados() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def caminhos() -> tuple[Path, Path]:
    dados = _dados()
    return (dados / "applications" / f"{NOME}.desktop",
            dados / "icons" / "hicolor" / "scalable" / "apps" / f"{NOME}.svg")  # fmt: skip


def executavel_axil() -> Path:
    """O `axil` em uso: o do PATH, se for o mesmo ambiente; senão, o que foi chamado agora."""
    # sem seguir links: ~/.local/bin/axil continua valendo depois de reinstalar
    chamado = Path(sys.argv[0]).absolute() if sys.argv and sys.argv[0] else None
    if chamado is not None and chamado.name == "axil" and chamado.is_file():
        return chamado
    no_path = shutil.which("axil")
    if no_path:
        return Path(no_path).absolute()
    vizinho = Path(sys.executable).with_name("axil")
    return vizinho if vizinho.is_file() else Path("axil")


def conteudo(executavel: Path) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Axillares
GenericName=Projeto de circuitos integrados
Comment=Do Verilog ao GDSII com ferramentas abertas
Exec="{executavel}" gui
Icon={NOME}
Terminal=false
Categories=Development;Electronics;Engineering;
Keywords=EDA;Verilog;ASIC;FPGA;GDSII;chip;
StartupWMClass={NOME}
StartupNotify=true
"""


def criar(executor: Executor | None = None) -> Atalho:
    executor = executor or ExecutorReal()
    desktop, icone = caminhos()
    exe = executavel_axil()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icone.parent.mkdir(parents=True, exist_ok=True)
    origem = Path(str(files("axillares.gui"))) / "icones" / "axillares.svg"
    shutil.copyfile(origem, icone)
    desktop.write_text(conteudo(exe), encoding="utf-8")
    desktop.chmod(0o755)
    _atualizar_caches(executor)
    return Atalho(desktop, icone, exe)


def remover(executor: Executor | None = None) -> list[Path]:
    removidos = []
    for caminho in caminhos():
        if caminho.exists():
            caminho.unlink()
            removidos.append(caminho)
    _atualizar_caches(executor or ExecutorReal())
    return removidos


def _atualizar_caches(executor: Executor) -> None:
    """Avisa o ambiente gráfico; os programas são opcionais (sem eles, aparece no próximo login)."""
    dados = _dados()
    executor.executar(["update-desktop-database", str(dados / "applications")], tempo_limite=20)
    executor.executar(["gtk-update-icon-cache", "-q", "-t", str(dados / "icons" / "hicolor")],
                      tempo_limite=20)  # fmt: skip
