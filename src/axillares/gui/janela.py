"""Janela principal: trilho de navegação à esquerda, telas à direita, sobre a trama."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from axillares import __version__
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.gui import tema as t
from axillares.gui.componentes import Ponto, Trama, regua, rotulo
from axillares.gui.telas.abertura import TelaAbertura
from axillares.gui.tema import Espaco, Modo, Papel

ICONE = t.PASTA / "icones" / "axillares.svg"

# (número, nome, disponível agora)
SECOES = (
    ("01", "Abertura", True),
    ("02", "Projeto", False),
    ("03", "Execuções", False),
    ("04", "Comparar", False),
    ("05", "Trilha", False),
)


class Trilho(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("trilho")
        self.setFixedWidth(Espaco.TRILHO)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, Espaco.L + 4, 0, Espaco.L)
        lay.setSpacing(0)

        marca = QHBoxLayout()
        marca.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        marca.setSpacing(6)
        marca.addWidget(Ponto(8, "acento", pulsar=True))
        marca.addWidget(rotulo("Axillares", Papel.MARCA))
        marca.addStretch(1)
        lay.addLayout(marca)
        sub = rotulo("Do Verilog ao GDSII", Papel.ROTULO, "3")
        sub.setContentsMargins(Espaco.M + 2 + 30, 2, 0, 0)
        lay.addWidget(sub)
        lay.addSpacing(Espaco.XL)

        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        for i, (numero, nome, disponivel) in enumerate(SECOES):
            b = QPushButton(f"{numero}   {nome}")
            b.setProperty("tipo", "nav")
            b.setFont(t.fonte(Papel.NAV))
            b.setCheckable(True)
            b.setEnabled(disponivel)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if not disponivel:
                b.setToolTip("Chega num dos próximos módulos.")
            self.grupo.addButton(b, i)
            lay.addWidget(b)
        self.grupo.button(0).setChecked(True)
        breve = rotulo("02–05 chegam nos próximos módulos", Papel.ROTULO, "3")
        breve.setWordWrap(True)
        breve.setContentsMargins(Espaco.M + 2, Espaco.M, Espaco.M, 0)
        lay.addWidget(breve)

        lay.addStretch(1)
        caixa = QVBoxLayout()
        caixa.setContentsMargins(Espaco.M + 2, 0, Espaco.M + 2, 0)
        caixa.setSpacing(Espaco.S + 2)
        caixa.addWidget(rotulo("Tema", Papel.ROTULO, "3"))
        segmentos = QHBoxLayout()
        segmentos.setSpacing(0)
        self.modos = QButtonGroup(self)
        for i, (modo, texto) in enumerate(
            ((Modo.ESCURO, "Escuro"), (Modo.CLARO, "Claro"), (Modo.SISTEMA, "Sistema"))
        ):
            b = QPushButton(texto)
            b.setProperty("tipo", "segmento")
            b.setProperty("posicao", "inicio" if i == 0 else "fim" if i == 2 else "meio")
            b.setFont(t.fonte(Papel.ETIQUETA))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(t.tema().modo is modo)
            b.clicked.connect(lambda _c=False, m=modo: t.tema().aplicar(m))
            self.modos.addButton(b, i)
            segmentos.addWidget(b)
        caixa.addLayout(segmentos)
        t.tema().mudou.connect(self._sincronizar_modo)
        caixa.addSpacing(Espaco.M)
        caixa.addWidget(regua())
        caixa.addSpacing(Espaco.S)
        caixa.addWidget(rotulo(f"v {__version__} · Apache-2.0", Papel.ROTULO, "3"))
        lay.addLayout(caixa)

    def _sincronizar_modo(self, _paleta: object) -> None:
        indice = (Modo.ESCURO, Modo.CLARO, Modo.SISTEMA).index(t.tema().modo)
        self.modos.button(indice).setChecked(True)


class JanelaPrincipal(QMainWindow):
    def __init__(
        self,
        perfil: Perfil | None = None,
        fabrica_executor: Callable[[], Executor] = ExecutorReal,
        verificar_ao_abrir: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Axillares")
        self.setWindowIcon(QIcon(str(ICONE)))
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)

        raiz = Trama()
        raiz.setObjectName("raiz")
        lay = QHBoxLayout(raiz)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.trilho = Trilho()
        lay.addWidget(self.trilho)
        self.pilha = QStackedWidget()
        lay.addWidget(self.pilha, 1)
        self.abertura = TelaAbertura(perfil or carregar_perfil(), fabrica_executor)
        self.pilha.addWidget(self.abertura)
        self.trilho.grupo.idClicked.connect(self.pilha.setCurrentIndex)
        self.setCentralWidget(raiz)
        if verificar_ao_abrir:
            self.abertura.verificar()

    def closeEvent(self, evento: QCloseEvent) -> None:
        self.abertura.encerrar()
        super().closeEvent(evento)


__all__ = ["JanelaPrincipal"]
