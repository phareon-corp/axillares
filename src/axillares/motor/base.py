"""Interface `Motor`: a fronteira fina entre Axillares e os orquestradores de terceiros.

Um motor recebe um projeto de Axillares e uma etapa e faz quatro coisas: prepara a configuração
dele, executa transmitindo o log ao vivo, coleta artefatos e coleta métricas — sempre devolvendo
modelos de Axillares (core.modelos), nunca o esquema do motor.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao
from axillares.core.projeto import Projeto


@dataclass
class Contexto:
    """Tudo o que um motor precisa saber sobre uma execução em curso."""

    projeto: Projeto
    etapa: Etapa
    id_execucao: str
    dir_trabalho: Path
    """Rascunho do motor; apagado ao fim da execução."""
    dir_saida: Path
    """Onde os artefatos ficam guardados (dentro do diretório imutável da execução)."""
    ao_receber: Callable[[str], None] = lambda _linha: None
    cancelar: threading.Event = field(default_factory=threading.Event)
    opcoes: dict = field(default_factory=dict)
    """Pedidos desta execução que não moram no axil.toml (ex.: filtro de testes)."""


class Motor(Protocol):
    nome: str

    def versao(self) -> str:
        """Versão fixada do motor, para o meta.json da execução."""
        ...

    def etapas(self) -> set[Etapa]: ...

    def preparar(self, ctx: Contexto) -> list[str]:
        """Escreve a configuração em `ctx.dir_trabalho`; devolve o comando que vai rodar."""
        ...

    def executar(self, ctx: Contexto) -> Situacao:
        """Executa, chamando `ctx.ao_receber` a cada linha de log. Respeita `ctx.cancelar`."""
        ...

    def coletar_artefatos(self, ctx: Contexto) -> list[Artefato]:
        """Copia os artefatos para `ctx.dir_saida` e os descreve (caminhos relativos a ele)."""
        ...

    def coletar_metricas(self, ctx: Contexto) -> list[Metrica]: ...

    def descrever_progresso(self, linha: str) -> str | None:
        """Se a linha de log marca o início de uma etapa do motor, devolve um rótulo legível."""
        ...

    def explicar_falha(self, ctx: Contexto) -> Falha | None:
        """Quando a execução falha: o que aconteceu, em linguagem de gente."""
        ...


class ErroMotor(Exception):
    """Motor indisponível ou mal configurado. A mensagem já está pronta para o usuário."""
