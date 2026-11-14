"""`axil novo`: cria um projeto a partir de um modelo embutido.

Cada modelo é uma pasta em templates/projetos/ com um `modelo.toml` (título, nível, descrição,
o que se aprende) e arquivos que podem usar variáveis Jinja no conteúdo e no nome:
nome, topo, pdk, frequencia_mhz, periodo_ns, atraso_ns.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from axillares.core.projeto import ErroProjeto, Pdk

TEMPLATES = Path(str(files("axillares.templates"))) / "projetos"
TEMPLATE_PADRAO = "vazio"
_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
_RENOMEAR = {"gitignore": ".gitignore"}


@dataclass(frozen=True)
class Modelo:
    id: str
    titulo: str
    nivel: str
    descricao: str
    ordem: int = 99
    aprende: list[str] = field(default_factory=list)
    topo_fixo: str | None = None


def modelos() -> list[Modelo]:
    lista = []
    for pasta in TEMPLATES.iterdir():
        ficha = pasta / "modelo.toml"
        if pasta.is_dir() and ficha.is_file():
            dados = tomllib.loads(ficha.read_text(encoding="utf-8"))
            lista.append(Modelo(id=pasta.name, **dados))
    return sorted(lista, key=lambda m: (m.ordem, m.id))


def templates_disponiveis() -> list[str]:
    return [m.id for m in modelos()]


def criar_projeto(
    nome: str,
    destino: Path,
    template: str = TEMPLATE_PADRAO,
    pdk: str = Pdk.SKYWATER130.value,
    frequencia_mhz: float = 100.0,
) -> Path:
    """Cria `destino/nome` a partir do modelo. Nunca sobrescreve uma pasta com conteúdo."""
    if not _NOME.match(nome):
        raise ErroProjeto(
            f"“{nome}” não serve como nome de projeto: use letras, números, _ ou -, começando "
            "por letra."
        )
    disponiveis = {m.id: m for m in modelos()}
    if template not in disponiveis:
        raise ErroProjeto(f"Modelo “{template}” não existe. Disponíveis: {', '.join(disponiveis)}.")
    if pdk not in {p.value for p in Pdk}:
        raise ErroProjeto(f"PDK “{pdk}” desconhecido. Use: {', '.join(p.value for p in Pdk)}.")
    if not 0 < frequencia_mhz <= 5000:
        raise ErroProjeto("A frequência precisa estar entre 0 e 5000 MHz.")
    modelo = disponiveis[template]
    pasta = destino / nome
    if pasta.exists() and any(pasta.iterdir()):
        raise ErroProjeto(f"A pasta {pasta} já existe e não está vazia; escolha outro nome.")

    periodo = 1000.0 / frequencia_mhz
    variaveis = {
        "nome": nome,
        "topo": modelo.topo_fixo or nome.replace("-", "_"),
        "pdk": pdk,
        "frequencia_mhz": f"{frequencia_mhz:g}",
        "periodo_ns": f"{periodo:.3f}".rstrip("0").rstrip("."),
        "atraso_ns": f"{periodo * 0.2:.3f}".rstrip("0").rstrip("."),
    }
    jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    origem = TEMPLATES / template
    for arquivo in sorted(origem.rglob("*")):
        if not arquivo.is_file() or "__pycache__" in arquivo.parts or arquivo.name == "modelo.toml":
            continue
        relativo = jinja.from_string(arquivo.relative_to(origem).as_posix()).render(**variaveis)
        caminho = Path(relativo)
        nome_final = _RENOMEAR.get(caminho.name, caminho.name)
        alvo = pasta / caminho.parent / nome_final.removesuffix(".j2")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if nome_final.endswith(".j2") or nome_final.endswith(".md"):
            texto = jinja.from_string(arquivo.read_text("utf-8")).render(**variaveis)
            alvo.write_text(texto, encoding="utf-8")
        else:
            alvo.write_bytes(arquivo.read_bytes())
    return pasta
