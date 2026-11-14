"""Trabalho fora da thread da interface. As tarefas só chamam funções do núcleo — as mesmas
que a CLI chama — e devolvem o resultado por sinal."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor
from axillares.ambiente.perfil import Perfil
from axillares.ambiente.verificacao import avaliar_ambiente
from axillares.core.caderno import ErroCaderno
from axillares.core.execucao import executar_etapa
from axillares.core.modelos import Etapa
from axillares.core.projeto import ErroProjeto, Projeto
from axillares.motor.base import ErroMotor, Motor

# Erros cuja mensagem já foi escrita para o usuário: mostrados como estão.
ERROS_DE_USUARIO = (ErroProjeto, ErroCaderno, ErroMotor)


class _Trabalhador(QObject):
    concluido = Signal(object)
    falhou = Signal(str)
    progresso = Signal(int, int, str)
    linha = Signal(str)
    iniciado = Signal(str)

    def __init__(self, funcao: Callable[[_Trabalhador], object]) -> None:
        super().__init__()
        self._funcao = funcao

    def rodar(self) -> None:
        try:
            self.concluido.emit(self._funcao(self))
        except ERROS_DE_USUARIO as erro:
            self.falhou.emit(str(erro))
        except Exception as erro:  # a interface precisa saber, nunca travar
            self.falhou.emit(f"{type(erro).__name__}: {erro}")


# Threads em andamento ficam aqui até terminarem de fato. Assim, se a tela dona de uma tarefa
# for destruída no meio (janela fechada, troca de projeto), a QThread não é destruída rodando
# — o que derrubaria o processo inteiro com "QThread: Destroyed while thread is still running".
_VIVAS: set[tuple[QThread, QObject]] = set()


def esperar_todas(ms: int = 30_000) -> None:
    for thread, _trab in list(_VIVAS):
        thread.wait(ms)


class Tarefa(QObject):
    """Uma execução em QThread própria; descartada ao terminar."""

    concluido = Signal(object)
    falhou = Signal(str)
    progresso = Signal(int, int, str)
    linha = Signal(str)
    iniciado = Signal(str)

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
        for nome in ("concluido", "falhou", "progresso", "linha", "iniciado"):
            getattr(self._trab, nome).connect(getattr(self, nome))
        # Conexão direta: quit() é seguro entre threads, e não pode depender do laço de eventos
        # da thread principal (que pode estar bloqueado esperando esta mesma thread).
        direta = Qt.ConnectionType.DirectConnection
        self._trab.concluido.connect(self._thread.quit, direta)
        self._trab.falhou.connect(self._thread.quit, direta)
        self.cancelar = threading.Event()
        par = (self._thread, self._trab)
        self._thread.finished.connect(lambda: _VIVAS.discard(par))
        self._par = par

    def iniciar(self) -> Tarefa:
        self._ativa = True
        _VIVAS.add(self._par)
        self._thread.start()
        return self

    def _terminar(self, *_: object) -> None:
        self._ativa = False

    def esperar(self, ms: int = 30_000) -> bool:
        return self._thread.wait(ms)

    @property
    def rodando(self) -> bool:
        return self._ativa


def em_segundo_plano(funcao: Callable[[], object], pai: QObject | None = None) -> Tarefa:
    """Leitura de disco, índice SQLite, etc. — nada disso na thread da interface."""
    return Tarefa(lambda _t: funcao(), pai)


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


def executar(projeto: Projeto, etapa: Etapa, motor: Motor, pai: QObject | None = None) -> Tarefa:
    """Mesma função da CLI (`executar_etapa`); `tarefa.cancelar.set()` interrompe."""
    tarefa: Tarefa

    def _rodar(trab: _Trabalhador) -> object:
        return executar_etapa(
            projeto,
            etapa,
            motor,
            ao_receber=trab.linha.emit,
            cancelar=tarefa.cancelar,
            ao_iniciar=trab.iniciado.emit,
        )

    tarefa = Tarefa(_rodar, pai)
    return tarefa
