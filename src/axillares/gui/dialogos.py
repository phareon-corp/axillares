"""Diálogo de projeto novo: escolher o modelo, o nome, a pasta, o PDK e o relógio."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from axillares.core.novo import Modelo, modelos
from axillares.gui import tema as t
from axillares.gui.componentes import botao, repolir, rotulo
from axillares.gui.tema import Espaco, Papel

PDKS = (
    ("skywater130", "SkyWater 130 nm (sky130)", "testado"),
    ("gf180", "GlobalFoundries 180 nm (gf180mcu)", "experimental"),
    ("ihp130", "IHP 130 nm (SG13G2)", "experimental"),
)
_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


class CartaoModelo(QFrame):
    escolhido = Signal(str)

    def __init__(self, m: Modelo, numero: int) -> None:
        super().__init__()
        self.modelo = m
        self.setProperty("tipo", "cartao-modelo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.M + 2, Espaco.M, Espaco.M + 2, Espaco.M)
        lay.setSpacing(6)
        topo = QHBoxLayout()
        topo.addWidget(rotulo(f"{numero:02d} /", Papel.NUMERO_SECAO, "acento"))
        topo.addWidget(rotulo(m.nivel, Papel.ROTULO, "3"))
        topo.addStretch(1)
        lay.addLayout(topo)
        lay.addWidget(rotulo(m.titulo, Papel.TITULO))
        desc = rotulo(m.descricao, Papel.PEQUENO, "2")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        if m.aprende:
            aprende = rotulo("aprende: " + " · ".join(m.aprende), Papel.ROTULO, "3")
            aprende.setWordWrap(True)
            lay.addWidget(aprende)
        lay.addStretch(1)
        self.setMinimumHeight(150)

    def marcar(self, sim: bool) -> None:
        self.setProperty("escolhido", "sim" if sim else "nao")
        repolir(self)

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.escolhido.emit(self.modelo.id)


class DialogoNovoProjeto(QDialog):
    def __init__(self, pai: QWidget | None = None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Novo projeto")
        self.setMinimumWidth(820)
        self.modelo_id = "vazio"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.XL, Espaco.XL, Espaco.XL, Espaco.L)
        lay.setSpacing(Espaco.M)
        lay.addWidget(rotulo("Novo projeto", Papel.ROTULO, "3"))
        titulo = rotulo(f"Por onde {t.serifa('começar', tamanho_px=30)}?", Papel.TITULO, rico=True)
        lay.addWidget(titulo)
        lay.addSpacing(Espaco.S)

        grade = QGridLayout()
        grade.setSpacing(Espaco.S + 2)
        self.cartoes: dict[str, CartaoModelo] = {}
        for i, m in enumerate(modelos()):
            c = CartaoModelo(m, i + 1)
            c.escolhido.connect(self._escolher)
            grade.addWidget(c, i // 2, i % 2)
            self.cartoes[m.id] = c
        lay.addLayout(grade)
        lay.addSpacing(Espaco.S)

        campos = QGridLayout()
        campos.setHorizontalSpacing(Espaco.M)
        campos.setVerticalSpacing(6)
        campos.addWidget(rotulo("Nome", Papel.ROTULO, "3"), 0, 0)
        campos.addWidget(rotulo("Criar dentro de", Papel.ROTULO, "3"), 0, 1)
        self.nome = QLineEdit("meu-chip")
        self.nome.setFont(t.fonte(Papel.CORPO))
        self.nome.textChanged.connect(self._validar)
        campos.addWidget(self.nome, 1, 0)
        pasta = QHBoxLayout()
        self.destino = QLineEdit(str(Path.home() / "Projetos"))
        self.destino.setFont(t.fonte(Papel.MONO))
        escolher = botao("Escolher…", "compacto")
        escolher.clicked.connect(self._escolher_pasta)
        pasta.addWidget(self.destino, 1)
        pasta.addWidget(escolher)
        campos.addLayout(pasta, 1, 1)
        campos.addWidget(rotulo("PDK (o processo de fabricação)", Papel.ROTULO, "3"), 2, 0)
        campos.addWidget(rotulo("Relógio alvo", Papel.ROTULO, "3"), 2, 1)
        self.pdk = QComboBox()
        self.pdk.setFont(t.fonte(Papel.CORPO))
        for valor, nome, situacao in PDKS:
            self.pdk.addItem(f"{nome}  ·  {situacao}", valor)
        campos.addWidget(self.pdk, 3, 0)
        self.frequencia = QDoubleSpinBox()
        self.frequencia.setFont(t.fonte(Papel.MONO))
        self.frequencia.setRange(1, 1000)
        self.frequencia.setDecimals(0)
        self.frequencia.setValue(100)
        self.frequencia.setSuffix(" MHz")
        campos.addWidget(self.frequencia, 3, 1)
        campos.setColumnStretch(0, 1)
        campos.setColumnStretch(1, 2)
        lay.addLayout(campos)

        self.aviso = rotulo("", Papel.PEQUENO, "falha")
        lay.addWidget(self.aviso)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = botao("Cancelar", "fantasma")
        cancelar.clicked.connect(self.reject)
        self.criar = botao("Criar projeto", "primario")
        self.criar.setDefault(True)
        self.criar.clicked.connect(self.accept)
        acoes.addWidget(cancelar)
        acoes.addWidget(self.criar)
        lay.addLayout(acoes)
        self._escolher("vazio")
        self._validar()

    def _escolher(self, ident: str) -> None:
        self.modelo_id = ident
        for i, c in self.cartoes.items():
            c.marcar(i == ident)

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Criar dentro de", self.destino.text())
        if pasta:
            self.destino.setText(pasta)

    def _validar(self) -> None:
        nome = self.nome.text().strip()
        ok = bool(_NOME.match(nome))
        self.aviso.setText("" if ok else "Use letras, números, _ ou -, começando por letra.")
        self.nome.setProperty("erro", "nao" if ok else "sim")
        repolir(self.nome)
        self.criar.setEnabled(ok)

    def escolhas(self) -> dict:
        return {
            "nome": self.nome.text().strip(),
            "destino": Path(self.destino.text()).expanduser(),
            "modelo": self.modelo_id,
            "pdk": self.pdk.currentData(),
            "frequencia_mhz": float(self.frequencia.value()),
        }
