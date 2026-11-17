"""Diálogo de exportação do esquemático: formato, estilo, prancha e carimbo."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from axillares.gui import tema as t
from axillares.gui.componentes import rotulo
from axillares.gui.exportar_esquema import Carimbo, OpcoesExportacao
from axillares.gui.tema import Espaco, Papel

FORMATOS = (
    ("prancha", "Prancha técnica (PDF, com moldura e carimbo)", ".pdf"),
    ("caderno", "Caderno de pranchas (PDF: todos os módulos e células)", ".pdf"),
    ("png", "Imagem PNG", ".png"),
    ("svg", "Vetor SVG (Inkscape, LibreOffice, CAD)", ".svg"),
    ("pdf", "PDF do tamanho do desenho", ".pdf"),
)


class DialogoExportar(QDialog):
    def __init__(self, carimbo: Carimbo, com_simulacao: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportar esquemático")
        self.setMinimumWidth(520)
        self._config = QSettings("Axillares", "axillares")
        col = QVBoxLayout(self)
        col.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.L)
        col.addWidget(rotulo("Exportar", Papel.EYEBROW, "acento"))
        form = QFormLayout()
        form.setSpacing(Espaco.S)

        self.formato = QComboBox()
        for chave, texto, _ext in FORMATOS:
            self.formato.addItem(texto, chave)
        self.formato.setCurrentIndex(max(0, self.formato.findData(
            self._config.value("esquema/exportar_formato", "prancha"))))  # fmt: skip
        self.formato.currentIndexChanged.connect(self._ajustar)
        form.addRow("Formato", self.formato)

        self.estilo = QComboBox()
        self.estilo.addItem("Impressão — preto no branco", "impressao")
        self.estilo.addItem("Cores do tema do app", "tema")
        self.estilo.setCurrentIndex(max(0, self.estilo.findData(
            self._config.value("esquema/exportar_estilo", "impressao"))))  # fmt: skip
        form.addRow("Estilo", self.estilo)

        self.folha = QComboBox()
        for nome in ("A4", "A3", "A2", "A1"):
            self.folha.addItem(nome, nome)
        self.folha.setCurrentIndex(max(0, self.folha.findData(
            self._config.value("esquema/exportar_folha", "A3"))))  # fmt: skip
        form.addRow("Folha", self.folha)

        self.escala = QComboBox()
        for fator in (1, 2, 4):
            self.escala.addItem(f"{fator}×", fator)
        self.escala.setCurrentIndex(1)
        form.addRow("Resolução", self.escala)
        self.transparente = QCheckBox("Fundo transparente")
        form.addRow("", self.transparente)

        self.titulo = QLineEdit(carimbo.titulo)
        self.autor = QLineEdit(carimbo.autor or str(self._config.value("esquema/autor", "")))
        self.revisao = QLineEdit(carimbo.revisao)
        self.revisao.setMaximumWidth(80)
        form.addRow("Título", self.titulo)
        form.addRow("Autor", self.autor)
        form.addRow("Revisão", self.revisao)
        self.legenda = QCheckBox("Legenda com os componentes do desenho")
        self.legenda.setChecked(True)
        form.addRow("", self.legenda)
        self.simulacao = QCheckBox("Valores da simulação no instante mostrado")
        self.simulacao.setEnabled(com_simulacao)
        self.simulacao.setChecked(com_simulacao)
        form.addRow("", self.simulacao)
        col.addLayout(form)

        self.nota = rotulo("", Papel.PEQUENO, "3")
        self.nota.setWordWrap(True)
        col.addWidget(self.nota)
        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.button(QDialogButtonBox.StandardButton.Save).setText("Escolher arquivo…")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        col.addWidget(botoes)
        self._carimbo = carimbo
        self._ajustar()
        self.setFont(t.fonte(Papel.CORPO))

    def _ajustar(self, *_args) -> None:
        f = self.formato.currentData()
        prancha = f in {"prancha", "caderno"}
        self.folha.setEnabled(prancha)
        for w in (self.titulo, self.autor, self.revisao, self.legenda):
            w.setEnabled(prancha)
        self.escala.setEnabled(f == "png")
        self.transparente.setEnabled(f in {"png", "svg"})
        self.nota.setText({
            "prancha": "Moldura com margem de arquivamento, zonas de referência (1, 2, 3… / A, "
            "B, C…) e carimbo com título, projeto, desenho, autor, data, revisão, escala e folha.",
            "caderno": "Uma prancha por página: cada módulo no nível atual e, no nível de células, "
            "os transistores de cada célula usada.",
            "png": "Imagem para documentos e apresentações; 4× serve para impressão grande.",
            "svg": "Vetorial: amplia sem perder qualidade e pode ser editado.",
            "pdf": "Vetorial, do tamanho exato do desenho.",
        }[f])  # fmt: skip

    @property
    def tipo(self) -> str:
        return self.formato.currentData()

    @property
    def extensao(self) -> str:
        return next(ext for chave, _t, ext in FORMATOS if chave == self.tipo)

    def opcoes(self) -> OpcoesExportacao:
        self._config.setValue("esquema/exportar_formato", self.tipo)
        self._config.setValue("esquema/exportar_estilo", self.estilo.currentData())
        self._config.setValue("esquema/exportar_folha", self.folha.currentData())
        self._config.setValue("esquema/autor", self.autor.text())
        c = self._carimbo
        carimbo = Carimbo(
            titulo=self.titulo.text(), projeto=c.projeto, nivel=c.nivel, descricao=c.descricao,
            autor=self.autor.text(), revisao=self.revisao.text() or "0", pdk=c.pdk,
        )  # fmt: skip
        return OpcoesExportacao(
            estilo=self.estilo.currentData(),
            escala_png=self.escala.currentData(),
            transparente=self.transparente.isChecked() and self.transparente.isEnabled(),
            prancha=self.folha.currentData() if self.tipo in {"prancha", "caderno"} else None,
            legenda=self.legenda.isChecked(),
            carimbo=carimbo,
        )
