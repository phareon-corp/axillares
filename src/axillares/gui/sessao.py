"""Sessão da interface: o projeto aberto e os avisos de mudança entre telas."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from axillares.core import recentes
from axillares.core.caderno import Caderno
from axillares.core.modelos import Etapa
from axillares.core.novo import criar_projeto
from axillares.core.projeto import Projeto, carregar_projeto
from axillares.gui import tarefas
from axillares.motor import ErroMotor, Motor, obter_motor


class Sessao(QObject):
    projeto_mudou = Signal(object)
    """Projeto aberto (ou None)."""
    execucoes_mudaram = Signal()
    """Uma execução terminou: listas e comparações devem recarregar."""
    erro = Signal(str)
    pedir_tela = Signal(str, object)
    """Navegação: (nome da tela, argumento)."""
    execucao_iniciada = Signal(object, str)
    """(etapa, nome do motor)"""
    execucao_linha = Signal(str, object)
    """(linha de log, passo legível ou None)"""
    execucao_concluida = Signal(object)
    """RegistroExecucao"""

    def __init__(self, fabrica_motor: Callable[[str], Motor] = obter_motor) -> None:
        super().__init__()
        self.projeto: Projeto | None = None
        self.fabrica_motor = fabrica_motor
        self._tarefas: list[tarefas.Tarefa] = []
        self._execucao: tarefas.Tarefa | None = None
        self.antes_de_executar: Callable[[Callable[[], None]], None] = lambda seguir: seguir()
        """Gancho: o editor o substitui para salvar arquivos pendentes antes de executar."""

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

    def criar(
        self,
        nome: str,
        destino: Path,
        modelo: str = "vazio",
        pdk: str = "skywater130",
        frequencia_mhz: float = 100.0,
    ) -> None:
        def criar() -> Projeto:
            projeto = carregar_projeto(criar_projeto(nome, destino, modelo, pdk, frequencia_mhz))
            recentes.registrar(projeto.raiz, projeto.nome)
            return projeto

        self._rodar(criar, self._definir)

    def _definir(self, projeto: Projeto) -> None:
        self.projeto = projeto
        self.projeto_mudou.emit(projeto)

    # --- execução ---------------------------------------------------------------------------

    @property
    def executando(self) -> bool:
        return bool(self._execucao and self._execucao.rodando)

    def executar(self, etapa: Etapa) -> bool:
        """Executa a etapa no projeto aberto (mesma função da CLI). False se não começou."""
        if self.projeto is None or self.executando:
            return False
        nome_motor = self.projeto.motores.para(etapa)
        try:
            motor = self.fabrica_motor(nome_motor)
        except ErroMotor as erro:
            self.erro.emit(str(erro))
            return False

        def comecar() -> None:
            projeto = self.projeto
            if projeto is None:
                return
            self._execucao = tarefas.executar(projeto, etapa, motor, self)
            self._execucao.linha.connect(
                lambda x: self.execucao_linha.emit(x, motor.descrever_progresso(x))
            )
            self._execucao.concluido.connect(self._concluida)
            self._execucao.falhou.connect(self.erro)
            self.execucao_iniciada.emit(etapa, nome_motor)
            self._execucao.iniciar()

        self.antes_de_executar(comecar)
        return True

    def cancelar(self) -> None:
        if self.executando:
            self._execucao.cancelar.set()

    def _concluida(self, registro) -> None:
        self.execucao_concluida.emit(registro)
        self.execucoes_mudaram.emit()

    def encerrar(self) -> None:
        if self.executando:
            self._execucao.cancelar.set()
            self._execucao.esperar(30_000)
        for t in self._tarefas:
            if t.rodando:
                t.cancelar.set()
                t.esperar(10_000)
