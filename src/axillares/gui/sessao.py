"""Sessão da interface: o projeto aberto e os avisos de mudança entre telas."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from axillares.core import recentes
from axillares.core.caderno import Caderno
from axillares.core.novo import criar_projeto
from axillares.core.projeto import Projeto, carregar_projeto
from axillares.gui import tarefas
from axillares.motor import Motor, obter_motor


class Sessao(QObject):
    projeto_mudou = Signal(object)
    """Projeto aberto (ou None)."""
    execucoes_mudaram = Signal()
    """Uma execução terminou: listas e comparações devem recarregar."""
    erro = Signal(str)
    pedir_tela = Signal(str, object)
    """Navegação: (nome da tela, argumento)."""

    def __init__(self, fabrica_motor: Callable[[str], Motor] = obter_motor) -> None:
        super().__init__()
        self.projeto: Projeto | None = None
        self.fabrica_motor = fabrica_motor
        self._tarefas: list[tarefas.Tarefa] = []

    @property
    def caderno(self) -> Caderno | None:
        return Caderno(self.projeto.dir_runs) if self.projeto else None

    def _rodar(self, funcao: Callable[[], object], ao_concluir: Callable[[object], None]) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(self.erro)
        self._tarefas = [t for t in self._tarefas if t.rodando] + [tarefa]
        tarefa.iniciar()

    def abrir(self, pasta: Path) -> None:
        def carregar() -> Projeto:
            projeto = carregar_projeto(pasta)
            recentes.registrar(projeto.raiz, projeto.nome)
            return projeto

        self._rodar(carregar, self._definir)

    def criar(self, nome: str, destino: Path) -> None:
        def criar() -> Projeto:
            projeto = carregar_projeto(criar_projeto(nome, destino))
            recentes.registrar(projeto.raiz, projeto.nome)
            return projeto

        self._rodar(criar, self._definir)

    def _definir(self, projeto: Projeto) -> None:
        self.projeto = projeto
        self.projeto_mudou.emit(projeto)

    def encerrar(self) -> None:
        for t in self._tarefas:
            if t.rodando:
                t.cancelar.set()
                t.esperar(10_000)
