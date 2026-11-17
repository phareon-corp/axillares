"""Ponto de entrada do comando `axil`."""

from __future__ import annotations

import platform

import typer
from rich.console import Console

from axillares import __version__
from axillares.cli import ambiente, projeto

app = typer.Typer(
    name="axil",
    help="Axillares — do Verilog ao GDSII com ferramentas abertas, sem montar o ambiente à mão.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
app.add_typer(ambiente.app, name="ambiente")
app.command("novo")(projeto.novo)
app.command("modelos")(projeto.modelos_cmd)
app.command("executar")(projeto.executar)
app.command("runs")(projeto.runs)
app.command("comparar")(projeto.comparar_cmd)
app.command("abrir")(projeto.abrir)
app.command("layout")(projeto.layout)
app.command("placas")(projeto.placas_cmd)
app.command("lint")(projeto.lint)
app.command("arquivo")(projeto.arquivo)
app.command("sim")(projeto.sim)
app.command("teste")(projeto.teste)
app.command("onda")(projeto.onda)
app.command("esquema")(projeto.esquema)


@app.callback()
def _raiz() -> None:
    """Axillares — do Verilog ao GDSII com ferramentas abertas."""


@app.command("versao")
def versao() -> None:
    """Mostra a versão do Axillares e do Python em uso."""
    console.print(f"axillares {__version__}")
    console.print(f"[dim]Python {platform.python_version()} · {platform.system()}[/dim]")


@app.command("gui")
def gui() -> None:
    """Abre a interface gráfica."""
    try:
        from axillares.gui.app import principal
    except ImportError as erro:
        console.print(
            "[bold red]✕[/] A interface gráfica precisa do PySide6, que não está instalado."
        )
        console.print("  → Instale com: [bold]pip install 'axillares[gui]'[/]")
        console.print(f"  [dim]{erro}[/dim]")
        raise typer.Exit(1) from erro
    falta = bibliotecas_do_sistema_faltando()
    if falta:
        console.print(
            f"[bold yellow]![/] A interface (Qt 6) pode não abrir: falta {', '.join(falta)} "
            "no sistema.\n  → Ubuntu/Debian: [bold]sudo apt install libxcb-cursor0 libegl1[/] · "
            "Fedora: [bold]sudo dnf install xcb-util-cursor mesa-libEGL[/]"
        )
    raise typer.Exit(principal())


def bibliotecas_do_sistema_faltando() -> list[str]:
    """Bibliotecas que o Qt 6 do PySide6 pede ao sistema e que costumam faltar (Ubuntu/Debian).

    Sem a libxcb-cursor, o Qt aborta no X11 com "could not load the Qt platform plugin xcb" e a
    janela simplesmente não aparece — inclusive ao clicar no ícone do menu.
    """
    import ctypes.util
    import os

    falta = []
    em_x11 = os.environ.get("XDG_SESSION_TYPE", "x11") != "wayland" or os.environ.get(
        "QT_QPA_PLATFORM", ""
    ).startswith("xcb")
    fora_da_tela = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    if em_x11 and not fora_da_tela and ctypes.util.find_library("xcb-cursor") is None:
        falta.append("libxcb-cursor")
    if ctypes.util.find_library("EGL") is None:
        falta.append("libEGL")
    return falta


@app.command("atalho")
def atalho(
    remover: bool = typer.Option(False, "--remover", help="Tira o atalho do menu."),
) -> None:
    """Põe o Axillares no menu de aplicativos, com ícone (ou tira, com --remover)."""
    from axillares.ambiente import atalho as at

    if remover:
        removidos = at.remover()
        console.print("[bold green]✓[/] Atalho removido." if removidos
                      else "Não havia atalho do Axillares no menu.")  # fmt: skip
        return
    feito = at.criar()
    console.print("[bold green]✓[/] Axillares no menu de aplicativos.")
    console.print(f"  [dim]atalho: {feito.desktop}[/dim]")
    console.print(f"  [dim]abre:   {feito.executavel} gui[/dim]")
    console.print("  Se não aparecer na hora, saia da sessão e entre de novo.")


if __name__ == "__main__":  # pragma: no cover
    app()
