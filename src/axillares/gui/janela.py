"""Janela principal: trilho de navegação à esquerda, telas à direita, sobre a trama."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares import __version__
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import Ponto, Trama, botao, regua, rotulo
from axillares.gui.sessao import Sessao
from axillares.gui.telas.abertura import TelaAbertura
from axillares.gui.telas.comparar import TelaComparar
from axillares.gui.telas.editor import TelaEditor
from axillares.gui.telas.execucoes import TelaExecucoes
from axillares.gui.telas.projeto import TelaProjeto
from axillares.gui.tema import Espaco, Modo, Papel
from axillares.motor import Motor, obter_motor

ICONE = t.PASTA / "icones" / "axillares.svg"

ABERTURA, PROJETO, EDITOR, EXECUCOES, COMPARAR = range(5)
# (número, nome, precisa de projeto aberto)
SECOES = (
    ("01", "Abertura", False),
    ("02", "Projeto", False),
    ("03", "Editor", True),
    ("04", "Execuções", True),
    ("05", "Comparar", True),
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
        self._precisam_projeto: list[QPushButton] = []
        for i, (numero, nome, precisa) in enumerate(SECOES):
            b = QPushButton(f"{numero}   {nome}")
            b.setProperty("tipo", "nav")
            b.setFont(t.fonte(Papel.NAV))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if precisa:
                b.setEnabled(False)
                b.setToolTip("Abra ou crie um projeto primeiro.")
                self._precisam_projeto.append(b)
            self.grupo.addButton(b, i)
            lay.addWidget(b)
        self.grupo.button(0).setChecked(True)

        lay.addSpacing(Espaco.L)
        self.projeto = rotulo("", Papel.ROTULO, "3")
        self.projeto.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        self.projeto.setWordWrap(True)
        lay.addWidget(self.projeto)
        breve = rotulo("06   Trilha · em breve", Papel.ROTULO, "3")
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

    def projeto_aberto(self, nome: str | None) -> None:
        for b in self._precisam_projeto:
            b.setEnabled(nome is not None)
            b.setToolTip("" if nome else "Abra ou crie um projeto primeiro.")
        self.projeto.setText(f"ABERTO: {nome}" if nome else "")


class FaixaAviso(QFrame):
    """Mensagem de erro passageira no rodapé — nunca um modal bloqueante."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("tipo", "faixa-progresso")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Espaco.MARGEM, Espaco.M - 2, Espaco.MARGEM, Espaco.M - 2)
        self.texto = rotulo("", Papel.CORPO)
        self.texto.setWordWrap(True)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(rotulo("✕", Papel.CORPO_FORTE, "falha"))
        lay.addWidget(self.texto, 1)
        fechar = botao("Fechar", "link")
        fechar.clicked.connect(self.hide)
        lay.addWidget(fechar)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def mostrar(self, mensagem: str) -> None:
        self.texto.setText(mensagem)
        self.show()
        self._timer.start(12_000)


class JanelaPrincipal(QMainWindow):
    def __init__(
        self,
        perfil: Perfil | None = None,
        fabrica_executor: Callable[[], Executor] = ExecutorReal,
        verificar_ao_abrir: bool = True,
        fabrica_motor: Callable[[str], Motor] = obter_motor,
        projeto_inicial: Path | None = None,
        fabrica_editor: Callable[[], QWidget] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Axillares")
        self.setWindowIcon(QIcon(str(ICONE)))
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)
        self.sessao = Sessao(fabrica_motor)
        self._pode_fechar = False

        raiz = Trama()
        raiz.setObjectName("raiz")
        lay = QHBoxLayout(raiz)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.trilho = Trilho()
        lay.addWidget(self.trilho)
        direita = QVBoxLayout()
        direita.setContentsMargins(0, 0, 0, 0)
        direita.setSpacing(0)
        self.pilha = QStackedWidget()
        direita.addWidget(self.pilha, 1)
        self.aviso = FaixaAviso()
        direita.addWidget(self.aviso)
        lay.addLayout(direita, 1)

        self.abertura = TelaAbertura(perfil or carregar_perfil(), fabrica_executor)
        self.projeto = TelaProjeto(self.sessao)
        self.editor = TelaEditor(self.sessao, fabrica_editor)
        self.execucoes = TelaExecucoes(self.sessao)
        self.comparar = TelaComparar(self.sessao)
        for tela in (self.abertura, self.projeto, self.editor, self.execucoes, self.comparar):
            self.pilha.addWidget(tela)

        self.trilho.grupo.idClicked.connect(self.ir_para)
        self.abertura.botao_novo.clicked.connect(self.projeto.novo_projeto)
        self.abertura.botao_abrir.clicked.connect(self.projeto.abrir_pasta)
        self.abertura.abrir_projeto.connect(self.sessao.abrir)
        self.execucoes.lista.comparar.connect(self._comparar)
        self.sessao.projeto_mudou.connect(self._projeto_mudou)
        self.sessao.erro.connect(self.aviso.mostrar)
        self.sessao.pedir_tela.connect(self._pedido_de_tela)
        self.setCentralWidget(raiz)

        self.abertura.carregar_recentes()
        if verificar_ao_abrir:
            self.abertura.verificar()
        if projeto_inicial is not None:
            self.sessao.abrir(projeto_inicial)

    def ir_para(self, indice: int) -> None:
        self.pilha.setCurrentIndex(indice)
        self.trilho.grupo.button(indice).setChecked(True)
        if indice == ABERTURA:
            self.abertura.carregar_recentes()

    def abrir_no_editor(self, caminho: Path, linha: int = 0, coluna: int = 1) -> None:
        self.ir_para(EDITOR)
        self.editor.abrir(caminho, linha, coluna)

    def _projeto_mudou(self, projeto) -> None:
        self.trilho.projeto_aberto(projeto.nome if projeto else None)
        self.setWindowTitle(f"{projeto.nome} — Axillares" if projeto else "Axillares")
        self.ir_para(PROJETO)

    def _comparar(self, a: str, b: str) -> None:
        self.comparar.pedir(a, b)
        self.ir_para(COMPARAR)

    def _pedido_de_tela(self, nome: str, argumento: object) -> None:
        if nome == "execucao":
            self.execucoes.abrir(str(argumento))
            self.ir_para(EXECUCOES)

    def closeEvent(self, evento: QCloseEvent) -> None:
        self.abertura.encerrar()
        self.sessao.encerrar()
        tarefas.esperar_todas()
        super().closeEvent(evento)


__all__ = ["JanelaPrincipal"]
