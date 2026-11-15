"""O que uma execução de simulação ou de teste deixou: casos de teste e a onda."""

from __future__ import annotations

import json
from pathlib import Path

from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import CasoTeste, SituacaoCaso, TipoArtefato

ARQUIVO_CASOS = "testes.json"


def casos(registro: RegistroExecucao) -> list[CasoTeste]:
    if registro.diretorio is None:
        return []
    arquivo = registro.diretorio / "saida" / ARQUIVO_CASOS
    if not arquivo.is_file():
        return []
    return [CasoTeste.model_validate(c) for c in json.loads(arquivo.read_text("utf-8"))]


def onda(registro: RegistroExecucao) -> Path | None:
    if registro.diretorio is None:
        return None
    for a in registro.artefatos:
        if a.tipo is TipoArtefato.ONDA:
            caminho = registro.diretorio / a.caminho
            if caminho.is_file():
                return caminho
    return None


def contagem(lista: list[CasoTeste]) -> dict[SituacaoCaso, int]:
    return {s: sum(1 for c in lista if c.situacao is s) for s in SituacaoCaso}
