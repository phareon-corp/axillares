"""Estrutura do arquivo aberto: módulos, sinais, funções — pelo servidor de linguagem (Verible)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from axillares.gui import tema as t
from axillares.gui.componentes import rotulo
from axillares.gui.tema import Espaco, Papel

PAPEL_POSICAO = Qt.ItemDataRole.UserRole


class PainelEstrutura(QFrame):
    ir = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("tipo", "lateral-editor")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, Espaco.M, 0, Espaco.S)
        lay.setSpacing(Espaco.S)
        cabeca = QVBoxLayout()
        cabeca.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        cabeca.setSpacing(2)
        cabeca.addWidget(rotulo("Estrutura", Papel.ROTULO, "3"))
        self.aviso = rotulo("", Papel.PEQUENO, "3")
        self.aviso.setWordWrap(True)
        cabeca.addWidget(self.aviso)
        lay.addLayout(cabeca)
        self.arvore = QTreeWidget()
        self.arvore.setHeaderHidden(True)
        self.arvore.setColumnCount(2)
        self.arvore.setIndentation(Espaco.M)
        self.arvore.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.arvore.itemClicked.connect(self._clicou)
        lay.addWidget(self.arvore, 1)
        self.mensagem("Abra um arquivo Verilog para ver a estrutura.")

    def mensagem(self, texto: str) -> None:
        self.arvore.clear()
        self.arvore.hide()
        self.aviso.setText(texto)
        self.aviso.show()

    def definir(self, simbolos: list[dict]) -> None:
        if not simbolos:
            self.mensagem("Nenhum módulo neste arquivo ainda.")
            return
        self.arvore.clear()
        pal = t.paleta()

        def item(s: dict) -> QTreeWidgetItem:
            novo = QTreeWidgetItem([s["nome"], s["tipo"]])
            novo.setFont(0, t.fonte(Papel.MONO))
            novo.setFont(1, t.fonte(Papel.ETIQUETA))
            novo.setForeground(1, pal.qcolor("tinta_3"))
            if s["tipo"] == "módulo":
                novo.setForeground(0, pal.qcolor("acento"))
            novo.setToolTip(0, f"{s['tipo']} · linha {s['linha']}")
            novo.setData(0, PAPEL_POSICAO, (s["linha"], s["coluna"]))
            for f in s.get("filhos", []):
                novo.addChild(item(f))
            return novo

        for s in simbolos:
            self.arvore.addTopLevelItem(item(s))
        self.arvore.expandAll()
        self.arvore.resizeColumnToContents(1)
        self.arvore.header().setStretchLastSection(False)
        self.arvore.header().setSectionResizeMode(0, self.arvore.header().ResizeMode.Stretch)
        self.aviso.hide()
        self.arvore.show()

    def _clicou(self, item: QTreeWidgetItem) -> None:
        posicao = item.data(0, PAPEL_POSICAO)
        if posicao:
            self.ir.emit(*posicao)
