"""Conteúdo didático (dado, não código): passos do fluxo, métricas, camadas e células.

Os textos moram em templates/explicacoes/*.toml. Este módulo só os carrega e casa nomes do motor
("place.global", "sky130_fd_sc_hd__dfrtp_1") com a explicação certa.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path

from axillares.core.modelos import Etapa

PASTA = Path(str(files("axillares.templates"))) / "explicacoes"


@dataclass(frozen=True)
class Passo:
    id: str
    titulo: str
    ferramenta: str
    o_que: str
    entra: str
    sai: str
    observar: str


@dataclass(frozen=True)
class ResumoEtapa:
    titulo: str
    resumo: str
    passos: list[Passo] = field(default_factory=list)


@dataclass(frozen=True)
class ExplicacaoMetrica:
    o_que: str
    leitura: str


@cache
def _ler(nome: str) -> dict:
    return tomllib.loads((PASTA / nome).read_text(encoding="utf-8"))


@cache
def passos() -> dict[str, Passo]:
    return {p["id"]: Passo(**p) for p in _ler("fluxo.toml")["passo"]}


def familia_do_no(no: str) -> str:
    """'synthesis.timing' → 'timing'; 'place.global' → 'place'; 'route.detailed/0' → 'route'."""
    base = no.split("/")[0]
    if "timing" in base:
        return "timing"
    return base.split(".")[0]


def passo_do_no(no: str) -> Passo | None:
    return passos().get(familia_do_no(no))


def etapa(etapa_: Etapa) -> ResumoEtapa:
    dados = _ler("fluxo.toml")["etapas"][etapa_.value]
    return ResumoEtapa(
        titulo=dados["titulo"],
        resumo=dados["resumo"],
        passos=[passos()[i] for i in dados["passos"]],
    )


def metrica(chave: str) -> ExplicacaoMetrica | None:
    dados = _ler("metricas.toml").get(chave)
    return ExplicacaoMetrica(**dados) if dados else None


def camada(nome: str) -> str | None:
    return _ler("sky130.toml")["camadas"].get(nome.split(" - ")[0])


def grupos_de_camadas() -> dict[str, list[str]]:
    return dict(_ler("sky130.toml")["grupos"])


_CELULA = re.compile(r"^(?:sky130_fd_sc_\w+?__)?(?P<familia>[a-z0-9]+?)(?:_(?P<forca>\d+))?$")


def celula(nome: str) -> tuple[str, str] | None:
    """('flip-flop…', 'força 1') para 'sky130_fd_sc_hd__dfrtp_1'; None se desconhecida."""
    achado = _CELULA.match(nome)
    if not achado:
        return None
    familia = achado["familia"]
    dados = _ler("sky130.toml")
    texto = dados["celulas"].get(familia)
    if texto is None:
        texto = next(
            (t for padrao, t in dados["padroes"].items() if re.match(padrao, familia)), None
        )
    if texto is None:
        return None
    forca = achado["forca"]
    detalhe = (
        f"força {forca}: transistores {'maiores' if forca != '1' else 'mínimos'}" if forca else ""
    )
    return texto, detalhe
