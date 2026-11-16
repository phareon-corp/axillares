"""Classes de máscaras: grupos de camadas do layout com nome e cor, que se ligam e desligam juntos.

Podem ser geradas automaticamente a partir das camadas presentes no GDS (pelos prefixos de
templates/explicacoes/<pdk>.toml, seção [classes]) ou criadas, editadas e removidas à mão. Ficam
no projeto, em .axil/classes-camadas.toml — uma por PDK — e valem para todos os layouts dele.

Camadas são identificadas pela fonte GDS ("64/20"): o nome muda de PDK para PDK, o número não.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field, field_validator

from axillares.core import explicacoes as ex

PASTA = ".axil"
ARQUIVO = "classes-camadas.toml"
_COR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FONTE = re.compile(r"^\d+/\d+$")


class ErroClasses(Exception):
    """Mensagem pronta para o usuário."""


class Classe(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    cor: str = "#A8A39A"
    camadas: list[str] = Field(default_factory=list, description="Fontes GDS, como 64/20.")

    @field_validator("cor")
    @classmethod
    def _cor(cls, valor: str) -> str:
        if not _COR.match(valor):
            raise ValueError("cor precisa ser #RRGGBB")
        return valor.upper()

    @field_validator("camadas")
    @classmethod
    def _fontes(cls, valor: list[str]) -> list[str]:
        ruins = [v for v in valor if not _FONTE.match(v)]
        if ruins:
            raise ValueError(f"camada fora do formato número/número: {', '.join(ruins)}")
        return list(dict.fromkeys(valor))


def gerar(camadas: list[tuple[str, str, str]], pdk: str) -> list[Classe]:
    """Classes automáticas. `camadas`: (nome, fonte, cor) das camadas presentes no layout.

    Cada camada vai para a primeira classe cujo prefixo casa com o nome dela (antes do ponto);
    a cor da classe é a da primeira camada. O que não casa com nada fica em "Outras"."""
    regras = ex.classes_de_camadas(pdk)
    classes: dict[str, Classe] = {}
    sobra: list[tuple[str, str, str]] = []
    for nome, fonte, cor in camadas:
        base = nome.split(" - ")[0].split(".")[0]
        destino = next((c for c, prefixos in regras.items() if base in prefixos), None)
        if destino is None:
            sobra.append((nome, fonte, cor))
            continue
        if destino not in classes:
            classes[destino] = Classe(nome=destino, cor=cor, camadas=[])
        classes[destino].camadas.append(fonte)
    ordem = [c for c in regras if c in classes]
    saida = [classes[c] for c in ordem]
    if sobra:
        saida.append(Classe(nome="Outras", cor=sobra[0][2], camadas=[f for _n, f, _c in sobra]))
    return saida


def caminho(raiz: Path) -> Path:
    return Path(raiz) / PASTA / ARQUIVO


def carregar(raiz: Path, pdk: str) -> list[Classe] | None:
    """As classes salvas do projeto para o PDK, ou None se nunca foram salvas."""
    arquivo = caminho(raiz)
    if not arquivo.is_file():
        return None
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        lista = dados.get(pdk, {}).get("classe")
        return None if lista is None else [Classe.model_validate(c) for c in lista]
    except (tomllib.TOMLDecodeError, ValueError) as erro:
        raise ErroClasses(f"{arquivo} tem problemas: {erro}") from erro


def salvar(raiz: Path, pdk: str, classes: list[Classe]) -> Path:
    nomes = [c.nome for c in classes]
    repetidos = {n for n in nomes if nomes.count(n) > 1}
    if repetidos:
        raise ErroClasses(f"Duas classes com o mesmo nome: {', '.join(sorted(repetidos))}.")
    arquivo = caminho(raiz)
    dados: dict = {}
    if arquivo.is_file():
        try:
            dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            dados = {}
    dados[pdk] = {"classe": [c.model_dump() for c in classes]}
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(
        "# Classes de máscaras do layout (Axillares). Edite pelo app ou aqui.\n"
        + tomli_w.dumps(dados),
        encoding="utf-8",
    )
    temporario.replace(arquivo)
    return arquivo
