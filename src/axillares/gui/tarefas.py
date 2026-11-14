"""Trabalho fora da thread da interface. As tarefas só chamam funções do núcleo — as mesmas
que a CLI chama — e devolvem o resultado por sinal."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor
from axillares.ambiente.perfil import Perfil
from axillares.ambiente.verificacao import avaliar_ambiente


class _Trabalhador(QObject):
    concluido = Signal(object)
    falhou = Signal(str)
    progresso = Signal(int, int, str)

    def __init__(self, funcao: Callable[[_Trabalhador], object]) -> None:
        super().__init__()
        self._funcao = funcao

    def rodar(self) -> None:
        try:
            self.concluido.emit(self._funcao(self))
        except Exception as erro:  # a interface precisa saber, nunca travar
            self.falhou.emit(f"{type(erro).__name__}: {erro}")


class Tarefa(QObject):
    """Uma execução em QThread própria; descartada ao terminar."""

    concluido = Signal(object)
    falhou = Signal(str)
    progresso = Signal(int, int, str)

    def __init__(self, funcao: Callable[[_Trabalhador], object], pai: QObject | None = None):
        super().__init__(pai)
        self._thread = QThread()
        self._trab = _Trabalhador(funcao)
        self._trab.moveToThread(self._thread)
        self._thread.started.connect(self._trab.rodar)
        self._ativa = False
        # marca o fim antes de repassar os sinais: quem recebe `concluido` já pode iniciar outra
        self._trab.concluido.connect(self._terminar)
        self._trab.falhou.connect(self._terminar)
        self._trab.concluido.connect(self.concluido)
        self._trab.falhou.connect(self.falhou)
        self._trab.progresso.connect(self.progresso)
        self._trab.concluido.connect(self._thread.quit)
        self._trab.falhou.connect(self._thread.quit)

    def iniciar(self) -> Tarefa:
        self._ativa = True
        self._thread.start()
        return self

    def _terminar(self, *_: object) -> None:
        self._ativa = False

    def esperar(self, ms: int = 30_000) -> bool:
        return self._thread.wait(ms)

    @property
    def rodando(self) -> bool:
        return self._ativa


def avaliar(perfil: Perfil, executor: Executor, pai: QObject | None = None) -> Tarefa:
    return Tarefa(lambda _t: avaliar_ambiente(perfil, executor), pai)


def instalar(perfil: Perfil, executor: Executor, pai: QObject | None = None) -> Tarefa:
    def _rodar(trab: _Trabalhador) -> object:
        programa = ct.detectar_programa(executor)
        if programa is None:
            from axillares.ambiente.diagnostico import sem_conteiner

            return ct.ResultadoInstalacao(False, sem_conteiner(), None)  # type: ignore[arg-type]
        return ct.baixar_imagem(
            programa,
            perfil.imagem,
            executor,
            lambda p: trab.progresso.emit(p.camadas, p.total, p.linha),
        )

    return Tarefa(_rodar, pai)
