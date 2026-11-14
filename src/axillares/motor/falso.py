"""MotorFalso: reproduz execuções gravadas. Para testes e demonstrações sem ferramentas."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao, TipoArtefato
from axillares.motor.base import Contexto


@dataclass
class Gravacao:
    """Uma execução gravada: o log, o desfecho e o que ela produziu."""

    log: list[str] = field(default_factory=lambda: ["executando…", "pronto"])
    situacao: Situacao = Situacao.SUCESSO
    metricas: list[Metrica] = field(default_factory=list)
    artefatos: dict[str, bytes] = field(default_factory=dict)
    falha: Falha | None = None
    versao: str = "0.0.0-falso"
    cancelar_na_linha: int | None = None
    """Simula o usuário cancelando quando esta linha do log for emitida."""


class MotorFalso:
    nome = "falso"

    def __init__(self, *gravacoes: Gravacao) -> None:
        self._fila = list(gravacoes) or [Gravacao()]
        self._atual: Gravacao | None = None
        self.preparados: list[Contexto] = []

    def versao(self) -> str:
        return self._fila[0].versao

    def etapas(self) -> set[Etapa]:
        return set(Etapa)

    def preparar(self, ctx: Contexto) -> list[str]:
        self._atual = self._fila.pop(0) if len(self._fila) > 1 else self._fila[0]
        self.preparados.append(ctx)
        ctx.dir_trabalho.mkdir(parents=True, exist_ok=True)
        return ["motor-falso", ctx.etapa.value, ctx.projeto.nome]

    def executar(self, ctx: Contexto) -> Situacao:
        assert self._atual is not None, "preparar() antes de executar()"
        for numero, linha in enumerate(self._atual.log):
            if self._atual.cancelar_na_linha == numero:
                ctx.cancelar.set()
            if ctx.cancelar.is_set():
                return Situacao.INTERROMPIDA
            ctx.ao_receber(linha)
        return self._atual.situacao

    def coletar_artefatos(self, ctx: Contexto) -> list[Artefato]:
        assert self._atual is not None
        ctx.dir_saida.mkdir(parents=True, exist_ok=True)
        artefatos = []
        for nome, conteudo in self._atual.artefatos.items():
            (ctx.dir_saida / nome).write_bytes(conteudo)
            tipo = TipoArtefato.GDS if ".gds" in nome else TipoArtefato.OUTRO
            artefatos.append(
                Artefato(nome=nome, tipo=tipo, caminho=Path("saida") / nome, bytes=len(conteudo))
            )
        return artefatos

    def coletar_metricas(self, ctx: Contexto) -> list[Metrica]:
        assert self._atual is not None
        return list(self._atual.metricas)

    def descrever_progresso(self, linha: str) -> str | None:
        return linha.removeprefix("etapa: ") if linha.startswith("etapa: ") else None

    def explicar_falha(self, ctx: Contexto) -> Falha | None:
        assert self._atual is not None
        return self._atual.falha
