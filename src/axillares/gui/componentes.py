"""Peças visuais reutilizáveis. Nenhuma cor literal: tudo vem de `tema`."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from axillares.gui import tema as t
from axillares.gui.tema import Espaco, Movimento, Papel


def repolir(w: QWidget) -> None:
    """Reaplica a folha de estilo depois de mudar uma propriedade dinâmica."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def rotulo(
    texto: str = "", papel: Papel = Papel.CORPO, tom: str | None = None, rico: bool = False
) -> QLabel:
    r = QLabel(texto)
    r.setFont(t.fonte(papel))
    if tom:
        r.setProperty("tom", tom)
    r.setTextFormat(Qt.TextFormat.RichText if rico else Qt.TextFormat.PlainText)
    r.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return r


def botao(texto: str, tipo: str = "fantasma") -> QPushButton:
    b = QPushButton(texto)
    b.setProperty("tipo", tipo)
    b.setFont(t.fonte(Papel.BOTAO))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def regua() -> QFrame:
    r = QFrame()
    r.setProperty("tipo", "regua")
    return r


def quadro(tipo: str) -> QFrame:
    q = QFrame()
    q.setProperty("tipo", tipo)
    return q


class Ponto(QWidget):
    """Ponto de sinal com halo. Com `pulsar`, respira em 3s: fonte ativa (Phareon)."""

    def __init__(self, diametro: int = 6, token: str = "acento", pulsar: bool = False) -> None:
        super().__init__()
        self._diametro = diametro
        self._token = token
        self._fase = 0.0
        lado = diametro * 3
        self.setFixedSize(lado, lado)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._anim: QVariantAnimation | None = None
        if pulsar and Movimento.animar:
            self._anim = QVariantAnimation(self)
            self._anim.setStartValue(0.0)
            self._anim.setKeyValueAt(0.5, 1.0)
            self._anim.setEndValue(0.0)
            self._anim.setDuration(Movimento.PULSO)
            self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._anim.setLoopCount(-1)
            self._anim.valueChanged.connect(self._ao_animar)
            self._anim.start()
        t.tema().mudou.connect(lambda _p: self.update())

    def definir_token(self, token: str) -> None:
        self._token = token
        self.update()

    def _ao_animar(self, valor: float) -> None:
        self._fase = float(valor)
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cor = t.paleta().qcolor(self._token)
        centro = QPointF(self.width() / 2, self.height() / 2)
        raio_halo = self._diametro * (1.2 + 0.3 * self._fase)
        halo = QRadialGradient(centro, raio_halo)
        brilho = QColor(cor)
        brilho.setAlphaF(0.45 + 0.25 * self._fase)
        transparente = QColor(cor)
        transparente.setAlphaF(0.0)
        halo.setColorAt(0.0, brilho)
        halo.setColorAt(1.0, transparente)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(centro, raio_halo, raio_halo)
        p.setBrush(cor)
        r = self._diametro / 2
        p.drawEllipse(centro, r, r)


class Eyebrow(QWidget):
    """Etiqueta do instrumento: ponto laranja + texto mono em caixa alta."""

    def __init__(self, texto: str, token: str = "acento") -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.ponto = Ponto(6, token)
        self.texto = rotulo(texto, Papel.EYEBROW, "2")
        lay.addWidget(self.ponto)
        lay.addWidget(self.texto)
        lay.addStretch(1)


class NumeroSecao(QWidget):
    """`01 / FERRAMENTAS` — numeral em acento, título em tinta secundária, régua embaixo."""

    def __init__(self, numero: str, titulo: str, apoio: str = "") -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Espaco.S + 2)
        topo = QHBoxLayout()
        topo.setSpacing(Espaco.S)
        topo.addWidget(rotulo(f"{numero} /", Papel.NUMERO_SECAO, "acento"))
        topo.addWidget(rotulo(titulo, Papel.NUMERO_SECAO, "2"))
        topo.addStretch(1)
        self.apoio = rotulo(apoio, Papel.ROTULO, "3")
        topo.addWidget(self.apoio)
        lay.addLayout(topo)
        lay.addWidget(regua())


class Pilula(QWidget):
    """Situação de uma verificação: contorno fino, ponto colorido, texto mono."""

    def __init__(self, texto: str = "", token: str = "tinta_3") -> None:
        super().__init__()
        self._texto = texto
        self._token = token
        self._fonte = t.fonte(Papel.ETIQUETA)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        t.tema().mudou.connect(lambda _p: self.update())

    def definir(self, texto: str, token: str) -> None:
        self._texto, self._token = texto, token
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        from PySide6.QtGui import QFontMetrics

        largura = QFontMetrics(self._fonte).horizontalAdvance(self._texto.upper())
        return QSize(largura + 34, 22)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = t.paleta()
        cor = pal.qcolor(self._token)
        borda = QColor(cor)
        borda.setAlphaF(0.45)
        fundo = QColor(cor)
        fundo.setAlphaF(0.08)
        caixa = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(borda, 1))
        p.setBrush(fundo)
        p.drawRoundedRect(caixa, caixa.height() / 2, caixa.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cor)
        p.drawEllipse(QPointF(12, caixa.center().y()), 3, 3)
        p.setPen(pal.qcolor("tinta"))
        p.setFont(self._fonte)
        p.drawText(caixa.adjusted(21, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, self._texto)


class Trama(QWidget):
    """Fundo com a trama de 80px e um halo laranja suave — a câmara escura onde a luz é medida."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._halo = 1.0
        t.tema().mudou.connect(lambda _p: self.update())

    def _get_halo(self) -> float:
        return self._halo

    def _set_halo(self, v: float) -> None:
        self._halo = v
        self.update()

    halo = Property(float, _get_halo, _set_halo)

    def paintEvent(self, _e: QPaintEvent) -> None:
        pal = t.paleta()
        p = QPainter(self)
        p.fillRect(self.rect(), pal.qcolor("fundo"))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # halo radial (wash) no alto à direita
        centro = QPointF(self.width() * 0.82, -self.height() * 0.05)
        raio = max(self.width(), self.height()) * 0.55
        g = QRadialGradient(centro, raio)
        acento = pal.qcolor("acento")
        acento.setAlphaF((0.16 if pal.escura else 0.10) * self._halo)
        nada = QColor(acento)
        nada.setAlphaF(0.0)
        g.setColorAt(0.0, acento)
        g.setColorAt(1.0, nada)
        p.fillRect(self.rect(), g)
        # trama
        linha = pal.qcolor("linha")
        linha.setAlphaF(linha.alphaF() * 0.75)
        p.setPen(QPen(linha, 1))
        passo = Espaco.TRAMA
        x = passo
        while x < self.width():
            p.drawLine(x, 0, x, self.height())
            x += passo
        y = passo
        while y < self.height():
            p.drawLine(0, y, self.width(), y)
            y += passo


class Metrica(QFrame):
    """Célula de métrica: rótulo mono, valor grande, unidade em serifa itálica, nota curta."""

    def __init__(self, rotulo_texto: str) -> None:
        super().__init__()
        self.setProperty("tipo", "celula")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.L)
        lay.setSpacing(Espaco.S + 2)
        self._rotulo = rotulo(rotulo_texto, Papel.ROTULO, "3")
        self._valor = rotulo("—", Papel.METRICA, rico=True)
        self._nota = rotulo("", Papel.PEQUENO, "2")
        self._nota.setWordWrap(True)
        lay.addWidget(self._rotulo)
        lay.addWidget(self._valor)
        lay.addWidget(self._nota)
        lay.addStretch(1)
        self.setMinimumWidth(170)
        self._ultimo: tuple[str, str, str] = ("—", "", "")
        t.tema().mudou.connect(lambda _p: self.definir(*self._ultimo))

    def definir(self, valor: str, unidade: str = "", nota: str = "") -> None:
        self._ultimo = (valor, unidade, nota)
        texto = valor
        if unidade:
            texto += "&#8202;" + t.serifa(unidade, t.paleta().tinta_2, 20)
        self._valor.setText(texto)
        self._nota.setText(nota)
