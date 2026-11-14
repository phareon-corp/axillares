"""Espaço de trabalho: vários projetos abertos ao mesmo tempo, cada um na sua área.

Cada `AreaProjeto` tem a própria Sessão (projeto, execução, editor, layout) — dá para executar
dois projetos em paralelo e comparar layouts de projetos diferentes lado a lado.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares.core.caderno import Caderno
from axillares.core.projeto import Projeto
from axillares.gui import tema as t
from axillares.gui.componentes import Ponto, botao, repolir, rotulo
from axillares.gui.sessao import Sessao
from axillares.gui.telas.comparar import TelaComparar
from axillares.gui.telas.editor import TelaEditor
from axillares.gui.telas.execucoes import TelaExecucoes
from axillares.gui.telas.layout import TelaLayout
from axillares.gui.telas.projeto import TelaProjeto
from axillares.gui.tema import Espaco, Papel
from axillares.motor import Motor

# índices das telas (01 Abertura é global e fica fora da área)
ABERTURA, PROJETO, EDITOR, EXECUCOES, LAYOUT, COMPARAR = range(6)

FontesDeExecucoes = Callable[[], list[tuple[str, Caderno]]]


class AreaProjeto(QWidget):
    """Um projeto aberto: a sessão dele e as cinco telas que trabalham sobre ele."""

    estado_mudou = Signal()

    def __init__(
        self,
        projeto: Projeto,
        fabrica_motor: Callable[[str], Motor],
        fabrica_editor: Callable[[], QWidget] | None,
        fontes: FontesDeExecucoes,
    ) -> None:
        super().__init__()
        self.sessao = Sessao(fabrica_motor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pilha = QStackedWidget()
        lay.addWidget(self.pilha)
        self.projeto = TelaProjeto(self.sessao)
        self.editor = TelaEditor(self.sessao, fabrica_editor)
        self.execucoes = TelaExecucoes(self.sessao)
        self.layout_ = TelaLayout(self.sessao, fontes)
        self.comparar = TelaComparar(self.sessao)
        for tela in (self.projeto, self.editor, self.execucoes, self.layout_, self.comparar):
            self.pilha.addWidget(tela)
        self.indice = PROJETO
        self.sessao.execucao_iniciada.connect(lambda *_: self.estado_mudou.emit())
        self.sessao.execucao_concluida.connect(lambda *_: self.estado_mudou.emit())
        self.editor.sujos_mudaram.connect(lambda *_: self.estado_mudou.emit())
        self.sessao.definir(projeto)

    @property
    def raiz(self):
        return self.sessao.projeto.raiz if self.sessao.projeto else None

    @property
    def nome(self) -> str:
        return self.sessao.projeto.nome if self.sessao.projeto else "?"

    def ir_para(self, indice: int) -> None:
        self.indice = indice
        self.pilha.setCurrentIndex(indice - PROJETO)
        if indice == LAYOUT:
            self.layout_.ao_mostrar()

    @property
    def executando(self) -> bool:
        return self.sessao.executando

    @property
    def tem_alteracoes(self) -> bool:
        return self.editor.tem_alteracoes

    def encerrar(self) -> None:
        self.layout_.encerrar()
        self.sessao.encerrar()


class AbaProjeto(QFrame):
    clicada = Signal(object)
    fechar = Signal(object)

    def __init__(self, area: AreaProjeto) -> None:
        super().__init__()
        self.area = area
        self.setProperty("tipo", "aba-projeto")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Espaco.M - 2, 0, 6, 0)
        lay.setSpacing(6)
        self.ponto = Ponto(6, "tinta_3", pulsar=True)
        lay.addWidget(self.ponto)
        self.nome = rotulo(area.nome, Papel.CORPO_FORTE)
        lay.addWidget(self.nome)
        self.estado = rotulo("", Papel.ETIQUETA, "acento")
        lay.addWidget(self.estado)
        fechar = QPushButton("×")
        fechar.setProperty("tipo", "fechar-aba")
        fechar.setFixedSize(20, 20)
        fechar.setCursor(Qt.CursorShape.PointingHandCursor)
        fechar.setToolTip("Fechar o projeto")
        fechar.clicked.connect(lambda: self.fechar.emit(self.area))
        lay.addWidget(fechar)
        self.setFixedHeight(40)
        area.estado_mudou.connect(self.atualizar)
        self.atualizar()

    def atualizar(self) -> None:
        self.nome.setText(self.area.nome)
        if self.area.executando:
            self.ponto.definir_token("acento")
            self.estado.setText("executando")
        else:
            self.ponto.definir_token("tinta_3")
            self.estado.setText("●" if self.area.tem_alteracoes else "")
        self.setToolTip(str(self.area.raiz or ""))

    def definir_ativa(self, ativa: bool) -> None:
        self.setProperty("ativa", "sim" if ativa else "nao")
        self.nome.setProperty("tom", None if ativa else "2")
        repolir(self)
        repolir(self.nome)

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicada.emit(self.area)
        elif evento.button() == Qt.MouseButton.MiddleButton:
            self.fechar.emit(self.area)


class BarraProjetos(QFrame):
    """Abas dos projetos abertos, mais Novo e Abrir."""

    novo = Signal()
    abrir = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("tipo", "barra-projetos")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, Espaco.M, 0)
        lay.setSpacing(0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rolagem.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setFixedHeight(40)
        faixa = QWidget()
        self._abas = QHBoxLayout(faixa)
        self._abas.setContentsMargins(0, 0, 0, 0)
        self._abas.setSpacing(0)
        self.vazio = rotulo("Nenhum projeto aberto", Papel.ETIQUETA, "3")
        self.vazio.setContentsMargins(Espaco.L, 0, 0, 0)
        self._abas.addWidget(self.vazio)
        self._abas.addStretch(1)
        rolagem.setWidget(faixa)
        lay.addWidget(rolagem, 1)
        for texto, sinal in (("+ Novo", self.novo), ("Abrir…", self.abrir)):
            b = botao(texto, "compacto")
            b.clicked.connect(sinal)
            lay.addSpacing(6)
            lay.addWidget(b)
        self.setFixedHeight(41)
        self.abas: list[AbaProjeto] = []

    def adicionar(self, aba: AbaProjeto) -> None:
        self._abas.insertWidget(self._abas.count() - 1, aba)
        self.abas.append(aba)
        self.vazio.hide()

    def remover(self, aba: AbaProjeto) -> None:
        self.abas.remove(aba)
        self._abas.removeWidget(aba)
        aba.deleteLater()
        self.vazio.setVisible(not self.abas)

    def ativar(self, area: AreaProjeto | None) -> None:
        for aba in self.abas:
            aba.definir_ativa(aba.area is area)


__all__ = [
    "ABERTURA",
    "COMPARAR",
    "EDITOR",
    "EXECUCOES",
    "LAYOUT",
    "PROJETO",
    "AreaProjeto",
    "BarraProjetos",
    "t",
]
