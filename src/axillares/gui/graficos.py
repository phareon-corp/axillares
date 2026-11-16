"""Gráficos simples desenhados com QPainter, na paleta do tema (sem biblioteca de gráficos)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from axillares.gui import tema as t
from axillares.gui.tema import Papel

ALTURA_BARRA = 22


@dataclass(frozen=True)
class Barra:
    rotulo: str
    fracao: float
    """De 0 a 1: o comprimento da barra."""
    texto: str
    """O número escrito ao lado (já com unidade)."""
    cor: QColor


class GraficoBarras(QWidget):
    """Barras horizontais: rótulo à esquerda, barra, valor à direita. Bom para comparar sinais."""

    def __init__(self, largura_rotulo: int = 150) -> None:
        super().__init__()
        self.barras: list[Barra] = []
        self.largura_rotulo = largura_rotulo
        self.vazio = "Nada para mostrar."
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(ALTURA_BARRA + 8)
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.update()

    def definir(self, barras: list[Barra], vazio: str = "Nada para mostrar.") -> None:
        self.barras = list(barras)
        self.vazio = vazio
        self.setFixedHeight(max(1, len(self.barras)) * ALTURA_BARRA + 8)
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        pal = t.paleta()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fonte = t.fonte(Papel.MONO)
        p.setFont(fonte)
        metrica = QFontMetrics(fonte)
        if not self.barras:
            p.setPen(pal.qcolor("tinta_3"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.vazio)
            return
        largura_texto = max(metrica.horizontalAdvance(b.texto) for b in self.barras) + 12
        area = max(10, self.width() - self.largura_rotulo - largura_texto - 8)
        for i, b in enumerate(self.barras):
            y = 4 + i * ALTURA_BARRA
            p.setPen(pal.qcolor("tinta_2"))
            rotulo = metrica.elidedText(b.rotulo, Qt.TextElideMode.ElideLeft,
                                        self.largura_rotulo - 10)  # fmt: skip
            direita = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            p.drawText(QRectF(0, y, self.largura_rotulo - 10, ALTURA_BARRA), direita, rotulo)
            trilho = QRectF(self.largura_rotulo, y + 5, area, ALTURA_BARRA - 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pal.qcolor("fundo_3"))
            p.drawRoundedRect(trilho, 3, 3)
            cheio = QRectF(trilho.left(), trilho.top(),
                           max(2.0, trilho.width() * min(max(b.fracao, 0.0), 1.0)),
                           trilho.height())  # fmt: skip
            p.setBrush(b.cor)
            p.drawRoundedRect(cheio, 3, 3)
            p.setPen(pal.qcolor("tinta"))
            p.drawText(QRectF(trilho.right() + 8, y, largura_texto, ALTURA_BARRA),
                       Qt.AlignmentFlag.AlignVCenter, b.texto)  # fmt: skip
        p.setBrush(Qt.BrushStyle.NoBrush)
