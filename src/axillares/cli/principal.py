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
app.command("executar")(projeto.executar)
app.command("runs")(projeto.runs)
app.command("comparar")(projeto.comparar_cmd)


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
    raise typer.Exit(principal())


if __name__ == "__main__":  # pragma: no cover
    app()
