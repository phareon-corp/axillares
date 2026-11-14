"""Ponto de entrada do comando `axil`."""

from __future__ import annotations

import platform

import typer
from rich.console import Console

from axillares import __version__
from axillares.cli import ambiente

app = typer.Typer(
    name="axil",
    help="Axillares — do Verilog ao GDSII com ferramentas abertas, sem montar o ambiente à mão.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
app.add_typer(ambiente.app, name="ambiente")


@app.callback()
def _raiz() -> None:
    """Axillares — do Verilog ao GDSII com ferramentas abertas."""


@app.command("versao")
def versao() -> None:
    """Mostra a versão do Axillares e do Python em uso."""
    console.print(f"axillares {__version__}")
    console.print(f"[dim]Python {platform.python_version()} · {platform.system()}[/dim]")


if __name__ == "__main__":  # pragma: no cover
    app()
