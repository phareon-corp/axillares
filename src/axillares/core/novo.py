"""`axil novo`: cria um projeto a partir de um template embutido."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from axillares.core.projeto import ErroProjeto

TEMPLATES = Path(str(files("axillares.templates"))) / "projetos"
TEMPLATE_PADRAO = "contador"
_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
_RENOMEAR = {"gitignore": ".gitignore"}


def templates_disponiveis() -> list[str]:
    return sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir())


def criar_projeto(nome: str, destino: Path, template: str = TEMPLATE_PADRAO) -> Path:
    """Cria `destino/nome` a partir do template. Nunca sobrescreve uma pasta com conteúdo."""
    if not _NOME.match(nome):
        raise ErroProjeto(
            f"“{nome}” não serve como nome de projeto: use letras, números, _ ou -, começando "
            "por letra."
        )
    origem = TEMPLATES / template
    if not origem.is_dir():
        raise ErroProjeto(
            f"Template “{template}” não existe. Disponíveis: {', '.join(templates_disponiveis())}."
        )
    pasta = destino / nome
    if pasta.exists() and any(pasta.iterdir()):
        raise ErroProjeto(f"A pasta {pasta} já existe e não está vazia; escolha outro nome.")

    jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    for arquivo in sorted(origem.rglob("*")):
        if not arquivo.is_file() or "__pycache__" in arquivo.parts:
            continue
        relativo = arquivo.relative_to(origem)
        nome_final = _RENOMEAR.get(relativo.name, relativo.name)
        texto_ou_bytes: str | bytes
        if nome_final.endswith(".j2") or nome_final.endswith(".md"):
            nome_final = nome_final.removesuffix(".j2")
            texto_ou_bytes = jinja.from_string(arquivo.read_text("utf-8")).render(nome=nome)
        else:
            texto_ou_bytes = arquivo.read_bytes()
        alvo = pasta / relativo.parent / nome_final
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(texto_ou_bytes, str):
            alvo.write_text(texto_ou_bytes, encoding="utf-8")
        else:
            alvo.write_bytes(texto_ou_bytes)
    return pasta
