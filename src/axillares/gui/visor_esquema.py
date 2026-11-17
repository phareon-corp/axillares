"""VisorEsquema: o circuito desenhado em notação técnica, na paleta Phareon.

O modelo (blocos, pinos, fios já em ângulo reto) vem de core/esquema.py; aqui só se desenha.
Portas na forma distintiva (E, OU, OU exclusivo, inversor com bolinha), multiplexador como
trapézio, registrador com o triângulo do relógio, células e módulos como circuito integrado com
o chanfro, transistores nMOS e pMOS, VDD e terra como nos livros.

Mouse: roda dá zoom no ponto do mouse; arrastar move; clique escolhe um bloco ou um fio (o fio
destaca a rede inteira); duplo clique entra (módulo → módulo, célula → transistores).
Teclado: + e −, F (ajustar), Esc (limpar escolha).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from axillares.core.esquema import Bloco, Esquema, Ligacao
from axillares.core.simulacao_esquema import LinhaDoTempo, formatar
from axillares.gui import tema as t
from axillares.gui.tema import Papel

ZOOM_MIN, ZOOM_MAX = 0.08, 6.0


@dataclass
class Cores:
    """As cores do desenho: as do tema do app, ou preto no branco para imprimir."""

    tinta: QColor
    fio: QColor
    acento: QColor
    fundo: QColor
    tenue: QColor
    destaque_texto: QColor
    nivel1: QColor
    nivel0: QColor
    indefinido: QColor
    solto: QColor
    barramento: QColor
    preencher: bool = True

    @classmethod
    def do_tema(cls) -> Cores:
        pal = t.paleta()
        return cls(
            tinta=pal.qcolor("tinta"), fio=pal.qcolor("tinta_2"), acento=pal.qcolor("acento"),
            fundo=pal.qcolor("fundo"), tenue=pal.qcolor("tinta_2"),
            destaque_texto=pal.qcolor("acento_brilho"), nivel1=pal.qcolor("ok"),
            nivel0=QColor(pal.series[1]), indefinido=pal.qcolor("falha"),
            solto=pal.qcolor("aviso"), barramento=QColor(pal.series[4]),
        )  # fmt: skip

    @classmethod
    def impressao(cls) -> Cores:
        c = {nome: QColor(valor) for nome, valor in t.IMPRESSAO.items()}
        return cls(
            tinta=c["tinta"], fio=c["tinta"], acento=c["acento"], fundo=c["fundo"],
            tenue=c["tenue"], destaque_texto=c["tinta"], nivel1=c["nivel1"], nivel0=c["nivel0"],
            indefinido=c["indefinido"], solto=c["solto"], barramento=c["barramento"],
            preencher=False,
        )  # fmt: skip


@dataclass
class EstadoSimulacao:
    """O que pintar por cima do desenho num instante da simulação."""

    linha: LinhaDoTempo
    t_ns: float
    transistores: tuple[dict[str, str], dict[str, bool | None]] | None = None
    """No nível de transistores: valor de cada nó e se cada transistor conduz."""

    def valor_ligacao(self, lig: Ligacao) -> str:
        if self.transistores is not None:
            return self.transistores[0].get(lig.rede, "?")
        return self.linha.valor(lig.bits, self.t_ns) if lig.bits else "?"

    def valor_pino(self, pino) -> str:
        if self.transistores is not None:
            return self.transistores[0].get(pino.rede_externa or pino.nome, "?")
        return self.linha.valor(pino.bits, self.t_ns) if pino.bits else "?"


_CORES: list[Cores] = []


def _cores() -> Cores:
    return _CORES[-1] if _CORES else Cores.do_tema()


def cor_do_valor(valor: str, cores: Cores) -> QColor | None:
    """1 verde, 0 azul, X vermelho, Z amarelo; barramento conhecido na cor de barramento."""
    if not valor or "?" in valor:
        return None
    if "x" in valor:
        return cores.indefinido
    if "z" in valor:
        return cores.solto
    if len(valor) > 1:
        return cores.barramento
    return cores.nivel1 if valor == "1" else cores.nivel0


CAIXAS_COM_PINOS = {"registrador", "latch", "celula", "modulo", "complexa", "somador_completo",
                    "memoria"}  # fmt: skip
NOMES_MUX = {"A": "0", "B": "1", "I0": "0", "I1": "1", "A0": "0", "A1": "1"}


class VisorEsquema(QWidget):
    bloco_escolhido = Signal(object)
    """Bloco escolhido (ou None)."""
    rede_escolhida = Signal(object)
    """Ligação escolhida (representa a rede inteira) ou None."""
    entrar = Signal(object)
    """Duplo clique num módulo ou numa célula: o Bloco."""
    entrada_clicada = Signal(object)
    """Na simulação, clique numa entrada do módulo (o Bloco): troca o valor dela."""

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.esquema: Esquema | None = None
        self.escala = 1.0
        self.desloc = QPointF(0, 0)
        self.escolhido: Bloco | None = None
        self.rede: Ligacao | None = None
        self.sobre: Bloco | None = None
        self.destacados: set[str] = set()
        self.estado: EstadoSimulacao | None = None
        self._arrasto: QPointF | None = None
        self._moveu = False
        self._ajustar_ao_mostrar = True
        t.tema().mudou.connect(lambda _p: self.update())

    def sizeHint(self) -> QSize:
        return QSize(800, 520)

    # --- API ----------------------------------------------------------------------------------

    def mostrar(self, esquema: Esquema | None) -> None:
        self.esquema = esquema
        self.escolhido = self.rede = self.sobre = None
        self.destacados = set()
        self._ajustar_ao_mostrar = True
        if self.width() > 50:
            self.ajustar()
        self.update()

    def ajustar(self) -> None:
        esq = self.esquema
        if esq is None or esq.largura <= 0:
            return
        margem = 16
        ex = (self.width() - 2 * margem) / esq.largura
        ey = (self.height() - 2 * margem) / esq.altura
        self.escala = max(ZOOM_MIN, min(1.6, ex, ey))
        self.desloc = QPointF(
            (self.width() - esq.largura * self.escala) / 2,
            (self.height() - esq.altura * self.escala) / 2,
        )
        self._ajustar_ao_mostrar = False
        self.update()

    def zoom(self, fator: float, centro: QPointF | None = None) -> None:
        centro = centro or QPointF(self.width() / 2, self.height() / 2)
        nova = max(ZOOM_MIN, min(ZOOM_MAX, self.escala * fator))
        cena = self._cena(centro)
        self.escala = nova
        self.desloc = centro - cena * nova
        self.update()

    def escolher(self, bloco: Bloco | None, centralizar: bool = False) -> None:
        self.escolhido = bloco
        self.rede = None
        if bloco is not None and centralizar:
            centro = QPointF(bloco.x + bloco.w / 2, bloco.y + bloco.h / 2)
            self.desloc = QPointF(self.width() / 2, self.height() / 2) - centro * self.escala
        self.update()

    def definir_estado(self, estado: EstadoSimulacao | None) -> None:
        self.estado = estado
        self.update()

    def destacar_tipo(self, tipo: str | None) -> None:
        esq = self.esquema
        self.destacados = {b.id for b in esq.blocos if b.tipo == tipo} if esq and tipo else set()
        self.update()

    # --- coordenadas e escolha ----------------------------------------------------------------

    def _cena(self, p: QPointF) -> QPointF:
        return (p - self.desloc) / self.escala

    def _bloco_em(self, p: QPointF) -> Bloco | None:
        if self.esquema is None:
            return None
        folga = 3 / self.escala
        for b in reversed(self.esquema.blocos):
            if b.simbolo == "juncao":
                continue
            if (
                b.x - folga <= p.x() <= b.x + b.w + folga
                and b.y - folga <= p.y() <= b.y + b.h + folga
            ):
                return b
        return None

    def _ligacao_em(self, p: QPointF) -> Ligacao | None:
        if self.esquema is None:
            return None
        limite = 5 / self.escala
        melhor, distancia = None, limite
        for lig in self.esquema.ligacoes:
            for a, b in zip(lig.pontos, lig.pontos[1:], strict=False):
                d = _distancia_segmento(p.x(), p.y(), a, b)
                if d < distancia:
                    melhor, distancia = lig, d
        return melhor

    def _mesma_rede(self, lig: Ligacao) -> bool:
        r = self.rede
        if r is None:
            return False
        return lig.de == r.de or (bool(r.rede) and lig.rede == r.rede)

    # --- eventos -------------------------------------------------------------------------------

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        if self._ajustar_ao_mostrar:
            self.ajustar()

    def wheelEvent(self, evento) -> None:
        passos = evento.angleDelta().y() / 120
        if passos:
            self.zoom(1.18**passos, evento.position())

    def mousePressEvent(self, evento) -> None:
        self.setFocus()
        if evento.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._arrasto = evento.position()
            self._moveu = False

    def mouseMoveEvent(self, evento) -> None:
        if self._arrasto is not None:
            delta = evento.position() - self._arrasto
            if self._moveu or abs(delta.x()) + abs(delta.y()) > 3:
                self._moveu = True
                self.desloc += delta
                self._arrasto = evento.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
            return
        sobre = self._bloco_em(self._cena(evento.position()))
        if sobre is not self.sobre:
            self.sobre = sobre
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if sobre else Qt.CursorShape.ArrowCursor
            )
            dica = _dica(sobre) if sobre else ""
            if sobre is not None and self.estado is not None and sobre.simbolo == "entrada":
                dica = "Clique para trocar o valor desta entrada a partir deste ciclo.\n" + dica
            self.setToolTip(dica)
            self.update()

    def mouseReleaseEvent(self, evento) -> None:
        arrastou = self._moveu
        self._arrasto = None
        self._moveu = False
        self.unsetCursor()
        if arrastou or evento.button() != Qt.MouseButton.LeftButton:
            return
        p = self._cena(evento.position())
        bloco = self._bloco_em(p)
        if bloco is not None:
            self.escolhido, self.rede = bloco, None
            self.bloco_escolhido.emit(bloco)
            if self.estado is not None and bloco.simbolo == "entrada":
                self.entrada_clicada.emit(bloco)
        else:
            lig = self._ligacao_em(p)
            self.escolhido, self.rede = None, lig
            self.bloco_escolhido.emit(None)
            self.rede_escolhida.emit(lig)
        self.update()

    def mouseDoubleClickEvent(self, evento) -> None:
        bloco = self._bloco_em(self._cena(evento.position()))
        if bloco is not None:
            self.entrar.emit(bloco)

    def keyPressEvent(self, evento) -> None:
        tecla = evento.key()
        if tecla in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(1.4)
        elif tecla == Qt.Key.Key_Minus:
            self.zoom(1 / 1.4)
        elif tecla == Qt.Key.Key_F:
            self.ajustar()
        elif tecla == Qt.Key.Key_Escape:
            self.escolhido = self.rede = None
            self.destacados = set()
            self.bloco_escolhido.emit(None)
            self.update()
        else:
            super().keyPressEvent(evento)

    # --- desenho -------------------------------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = t.paleta()
        p.fillRect(self.rect(), pal.qcolor("fundo"))
        self._trama(p)
        if self.esquema is None or not self.esquema.posicionado:
            return
        p.translate(self.desloc)
        p.scale(self.escala, self.escala)
        desenhar_esquema(p, self.esquema, self.escala, self.escolhido, self.rede, self.sobre,
                         self.destacados, self._mesma_rede, estado=self.estado)  # fmt: skip

    def _trama(self, p: QPainter) -> None:
        passo = 24 * self.escala
        if passo < 8:
            return
        cor = QColor(t.paleta().qcolor("tinta_3"))
        cor.setAlphaF(0.16)
        p.setPen(QPen(cor, 1.2))
        x0 = self.desloc.x() % passo
        y0 = self.desloc.y() % passo
        y = y0
        while y < self.height():
            x = x0
            while x < self.width():
                p.drawPoint(QPointF(x, y))
                x += passo
            y += passo


def _distancia_segmento(px: float, py: float, a: tuple, b: tuple) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    comprimento = dx * dx + dy * dy
    u = (
        0.0
        if comprimento == 0
        else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / comprimento))
    )
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


def _dica(b: Bloco) -> str:
    linhas = [b.tipo if b.tipo not in ("porta", "pino", "constante") else b.rotulo]
    if b.instancia and b.instancia != linhas[0]:
        linhas.append(b.instancia)
    if b.explicacao:
        linhas.append(b.explicacao)
    return "\n".join(linhas)


# --- desenho do esquema (também usado para exportar SVG/PNG) ---------------------------------


def desenhar_esquema(
    p: QPainter,
    esq: Esquema,
    escala: float = 1.0,
    escolhido: Bloco | None = None,
    rede: Ligacao | None = None,
    sobre: Bloco | None = None,
    destacados: set[str] | None = None,
    mesma_rede=None,
    cores: Cores | None = None,
    estado: EstadoSimulacao | None = None,
) -> None:
    cores = cores or Cores.do_tema()
    _CORES.append(cores)
    try:
        _desenhar(p, esq, escala, escolhido, sobre, destacados or set(), mesma_rede, cores,
                  estado)  # fmt: skip
    finally:
        _CORES.pop()


def _desenhar(p, esq, escala, escolhido, sobre, destacados, mesma_rede, cores, estado) -> None:
    com_texto = escala >= 0.3
    ligadas = set()
    if escolhido is not None:
        ligadas = {
            i for i, lig in enumerate(esq.ligacoes) if escolhido.id in (lig.de[0], lig.para[0])
        }
    fonte = QFont(t.fonte(Papel.MONO))
    fonte.setPixelSize(10)
    fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
    fonte.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    p.setFont(fonte)

    # fios (com simulação: na cor do valor)
    rotulos_de_valor: list[tuple[Ligacao, str, QColor]] = []
    for i, lig in enumerate(esq.ligacoes):
        if len(lig.pontos) < 2:
            continue
        realce = i in ligadas or (mesma_rede is not None and mesma_rede(lig))
        cor = cores.acento if realce else cores.fio
        largura = (2.6 if lig.largura > 1 else 1.3) + (0.6 if realce else 0)
        if estado is not None:
            valor = estado.valor_ligacao(lig)
            cor_valor = cor_do_valor(valor, cores)
            if cor_valor is not None and not realce:
                cor = cor_valor
                largura += 0.5
            if lig.largura > 1 and valor and "?" not in valor:
                rotulos_de_valor.append((lig, valor, cor))
        p.setPen(QPen(cor, largura, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                      Qt.PenJoinStyle.MiterJoin))  # fmt: skip
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in lig.pontos]))
        if lig.largura > 1 and com_texto:
            _marca_barramento(p, lig, cor)
    # junções
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cores.fio)
    for x, y in esq.juncoes:
        p.drawEllipse(QPointF(x, y), 2.8, 2.8)

    # blocos
    for b in esq.blocos:
        if b.simbolo == "juncao":
            if com_texto and b.detalhes.get("pino"):
                _rotulo_de_pino(p, b, cores.acento if b is escolhido else cores.tinta)
            continue
        cor = cores.acento if (b is escolhido or b.id in destacados) else cores.tinta
        desenhar_bloco(p, b, cor, com_texto, sobre=b is sobre, estado=estado)

    # valores dos barramentos, por cima de tudo
    if com_texto:
        for lig, valor, cor in rotulos_de_valor:
            _valor_no_fio(p, lig, formatar(valor), cor)


def _valor_no_fio(p: QPainter, lig: Ligacao, texto: str, cor: QColor) -> None:
    """O número que o barramento carrega, num selo sobre o trecho horizontal mais longo."""
    trechos = [(a, b) for a, b in zip(lig.pontos, lig.pontos[1:], strict=False)
               if abs(a[1] - b[1]) < 0.5]  # fmt: skip
    if not trechos:
        return
    a, b = max(trechos, key=lambda ab: abs(ab[1][0] - ab[0][0]))
    if abs(b[0] - a[0]) < 30:
        return
    _selo(p, QPointF((a[0] + b[0]) / 2, a[1]), texto, cor)


def _selo(p: QPainter, centro: QPointF, texto: str, cor: QColor) -> None:
    f = QFont(p.font())
    f.setPixelSize(9)
    f.setBold(True)
    p.save()
    p.setFont(f)
    largura = QFontMetricsF(f).horizontalAdvance(texto) + 8
    r = QRectF(centro.x() - largura / 2, centro.y() - 7, largura, 13)
    p.setPen(QPen(cor, 1.0))
    p.setBrush(_cores().fundo)
    p.drawRoundedRect(r, 3, 3)
    p.setPen(cor)
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, texto)
    p.restore()


def _rotulo_de_pino(p: QPainter, b: Bloco, cor: QColor) -> None:
    """Saída (ou entrada que passa por um canal) de uma célula, escrita junto da junção."""
    cx, cy = b.x + b.w / 2, b.y + b.h / 2
    f = QFont(p.font())
    f.setPixelSize(11)
    f.setBold(True)
    p.save()
    p.setFont(f)
    largura = QFontMetricsF(f).horizontalAdvance(b.rotulo) + 14
    r = QRectF(cx + 10, cy - 8, largura, 16)
    p.setPen(_caneta(cor, 1.3))
    p.setBrush(_cores().fundo)
    p.drawLine(QPointF(cx, cy), QPointF(r.left(), cy))
    p.drawPolygon(QPolygonF([r.topLeft(), QPointF(r.right() - 6, r.top()),
                             QPointF(r.right(), cy), QPointF(r.right() - 6, r.bottom()),
                             r.bottomLeft()]))  # fmt: skip
    p.setPen(cor)
    p.drawText(r.adjusted(4, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, b.rotulo)
    p.restore()


def _marca_barramento(p: QPainter, lig: Ligacao, cor: QColor) -> None:
    (x0, y0), (x1, y1) = lig.pontos[0], lig.pontos[1]
    horizontal = abs(y1 - y0) < 0.5
    mx, my = (x0 + 12, y0) if horizontal else (x0, y0 + 12)
    if math.hypot(x1 - x0, y1 - y0) < 16:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    p.setPen(QPen(cor, 1.2))
    p.drawLine(QPointF(mx - 4, my + 5), QPointF(mx + 4, my - 5))
    p.setPen(cor)
    p.drawText(QPointF(mx + 3, my - 6), str(lig.largura))


def _caneta(cor: QColor, largura: float = 1.6) -> QPen:
    return QPen(cor, largura, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin)  # fmt: skip


def _preenchimento(cor: QColor, alfa: float = 0.07) -> QColor:
    if not _cores().preencher:
        return QColor(0, 0, 0, 0)
    c = QColor(cor)
    c.setAlphaF(alfa)
    return c


def _texto_centro(p: QPainter, r: QRectF, texto: str, cor: QColor, tamanho: int = 10,
                  negrito: bool = False) -> None:  # fmt: skip
    f = QFont(p.font())
    f.setPixelSize(tamanho)
    f.setBold(negrito)
    p.save()
    p.setFont(f)
    p.setPen(cor)
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, texto)
    p.restore()


def _bolinha(p: QPainter, x: float, y: float, cor: QColor) -> None:
    p.setPen(_caneta(cor))
    p.setBrush(_cores().fundo)
    p.drawEllipse(QPointF(x + 3.5, y), 3.5, 3.5)


def desenhar_bloco(p: QPainter, b: Bloco, cor: QColor, com_texto: bool = True,
                   sobre: bool = False, estado: EstadoSimulacao | None = None) -> None:  # fmt: skip
    s = b.simbolo
    x, y, w, h = b.x, b.y, b.w, b.h
    p.save()
    p.setPen(_caneta(cor))
    p.setBrush(_preenchimento(cor, 0.12 if sobre else 0.06))
    negado = s in {"nand", "nor", "xnor", "not"}
    corpo_w = w - 8 if negado else w  # espaço para a bolinha
    if s in {"and", "nand"}:
        _porta_e(p, x, y, corpo_w, h)
    elif s in {"or", "nor"}:
        _porta_ou(p, x, y, corpo_w, h)
    elif s in {"xor", "xnor"}:
        _porta_ou(p, x + 5, y, corpo_w - 5, h)
        traseira = QPainterPath(QPointF(x, y))
        traseira.quadTo(QPointF(x + corpo_w * 0.22, y + h / 2), QPointF(x, y + h))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(traseira)
    elif s in {"not", "buf", "tribuf"}:
        p.drawPolygon(QPolygonF([QPointF(x, y + 2), QPointF(x + corpo_w, y + h / 2),
                                 QPointF(x, y + h - 2)]))  # fmt: skip
        if s == "tribuf":
            p.drawLine(QPointF(x + corpo_w / 2, y + h / 4 + 2), QPointF(x + corpo_w / 2, y - 4))
    elif s == "mux":
        inset = h * 0.18
        p.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x + w, y + inset),
                                 QPointF(x + w, y + h - inset), QPointF(x, y + h)]))  # fmt: skip
    elif s in {"operador", "comparador", "deslocador"}:
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
        if com_texto:
            _texto_centro(p, QRectF(x, y, w, h), b.rotulo, cor, 18 if len(b.rotulo) <= 2 else 12,
                          negrito=True)  # fmt: skip
    elif s in {"registrador", "latch"}:
        p.drawRect(QRectF(x, y, w, h))
    elif s in {"celula", "modulo", "complexa", "somador_completo", "memoria"}:
        _circuito_integrado(p, x, y, w, h, s == "modulo")
    elif s in {"entrada", "saida", "bidir"}:
        ponta = 8
        if s == "entrada":
            pontos = [(x, y), (x + w - ponta, y), (x + w, y + h / 2), (x + w - ponta, y + h),
                      (x, y + h)]  # fmt: skip
        elif s == "saida":
            pontos = [(x, y + h / 2), (x + ponta, y), (x + w, y), (x + w, y + h),
                      (x + ponta, y + h)]  # fmt: skip
        else:
            pontos = [(x, y + h / 2), (x + ponta, y), (x + w - ponta, y), (x + w, y + h / 2),
                      (x + w - ponta, y + h), (x + ponta, y + h)]  # fmt: skip
        p.drawPolygon(QPolygonF([QPointF(a, c) for a, c in pontos]))
        if com_texto:
            _texto_ajustado(p, QRectF(x + 4, y, w - 10, h), b.rotulo, cor)
    elif s == "rotulo":
        tenue = _cores().tenue if cor == _cores().tinta else cor
        p.setPen(_caneta(tenue, 1.1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        ponta = 6
        if b.pinos and b.pinos[0].lado == "e":  # etiqueta que alimenta um pino: aponta para ele
            pontos = [(x, y), (x + w - ponta, y), (x + w, y + h / 2), (x + w - ponta, y + h),
                      (x, y + h)]  # fmt: skip
        else:
            pontos = [(x, y + h / 2), (x + ponta, y), (x + w, y), (x + w, y + h),
                      (x + ponta, y + h)]  # fmt: skip
        p.drawPolygon(QPolygonF([QPointF(a, c) for a, c in pontos]))
        if com_texto:
            f = QFont(p.font())
            f.setPixelSize(9)
            p.setFont(f)
            _texto_ajustado(p, QRectF(x + 5, y, w - 9, h), b.rotulo, tenue)
    elif s == "constante":
        p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        if com_texto:
            _texto_centro(p, QRectF(x, y, w, h), b.rotulo, cor)
    elif s == "vdd":
        p.drawLine(QPointF(x + w / 2, y + h), QPointF(x + w / 2, y + 7))
        p.drawLine(QPointF(x + 3, y + 7), QPointF(x + w - 3, y + 7))
        if com_texto:
            _texto_centro(p, QRectF(x - 14, y - 9, w + 28, 12), b.rotulo, cor, 9)
    elif s == "gnd":
        cx = x + w / 2
        p.drawLine(QPointF(cx, y), QPointF(cx, y + 8))
        for i, meia in enumerate((w / 2 - 2, w / 3, w / 6)):
            yy = y + 8 + i * 4
            p.drawLine(QPointF(cx - meia, yy), QPointF(cx + meia, yy))
    elif s in {"nmos", "pmos"}:
        conduz = estado.transistores[1].get(b.instancia) if estado and estado.transistores \
            else None  # fmt: skip
        _transistor(p, b, cor, com_texto, conduz, estado)

    if negado:
        _bolinha(p, x + corpo_w, y + h / 2, cor)
    if com_texto:
        _rotulos_internos(p, b, cor)
        if estado is not None:
            _valores_do_bloco(p, b, estado)
    p.restore()


def _valores_do_bloco(p: QPainter, b: Bloco, estado: EstadoSimulacao) -> None:
    """Valores no instante: junto dos terminais do módulo e dentro dos registradores."""
    cores = _cores()
    if b.simbolo in {"entrada", "saida", "bidir"} and b.pinos:
        valor = estado.valor_pino(b.pinos[0])
        if "?" in valor:
            return
        cor = cor_do_valor(valor, cores) or cores.tinta
        texto = formatar(valor)
        largura = QFontMetricsF(p.font()).horizontalAdvance(texto) + 12
        cx = b.x - largura / 2 - 4 if b.simbolo == "entrada" else b.x + b.w + largura / 2 + 4
        _selo(p, QPointF(cx, b.y + b.h / 2), texto, cor)
    elif b.simbolo in {"registrador", "latch"}:
        q = next((pn for pn in b.pinos if pn.direcao == "saida"), None)
        if q is None:
            return
        valor = estado.valor_pino(q)
        if "?" not in valor:
            # o que o registrador guarda, num selo logo abaixo da caixa
            cor = cor_do_valor(valor, cores) or cores.tinta
            _selo(p, QPointF(b.x + b.w / 2, b.y + b.h + 9), f"Q = {formatar(valor)}", cor)


def _porta_e(p: QPainter, x: float, y: float, w: float, h: float) -> None:
    caminho = QPainterPath(QPointF(x, y))
    reto = w - h / 2 if w > h / 2 else w * 0.4
    caminho.lineTo(x + reto, y)
    caminho.arcTo(QRectF(x + reto - (w - reto), y, 2 * (w - reto), h), 90, -180)
    caminho.lineTo(x, y + h)
    caminho.closeSubpath()
    p.drawPath(caminho)


def _porta_ou(p: QPainter, x: float, y: float, w: float, h: float) -> None:
    caminho = QPainterPath(QPointF(x, y))
    caminho.quadTo(QPointF(x + w * 0.6, y), QPointF(x + w, y + h / 2))
    caminho.quadTo(QPointF(x + w * 0.6, y + h), QPointF(x, y + h))
    caminho.quadTo(QPointF(x + w * 0.22, y + h / 2), QPointF(x, y))
    p.drawPath(caminho)


def _circuito_integrado(p: QPainter, x: float, y: float, w: float, h: float, forte: bool) -> None:
    p.drawRect(QRectF(x, y, w, h))
    p.setBrush(Qt.BrushStyle.NoBrush)
    raio = min(7.0, w / 8)
    p.drawArc(QRectF(x + w / 2 - raio, y - raio, 2 * raio, 2 * raio), 180 * 16, 180 * 16)
    if forte:
        p.drawRect(QRectF(x + 3, y + 3, w - 6, h - 6))


def _texto_ajustado(p: QPainter, r: QRectF, texto: str, cor: QColor) -> None:
    metricas = QFontMetricsF(p.font())
    p.setPen(cor)
    p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
               metricas.elidedText(texto, Qt.TextElideMode.ElideRight, r.width()))  # fmt: skip


def _transistor(
    p: QPainter,
    b: Bloco,
    cor: QColor,
    com_texto: bool,
    conduz: bool | None = None,
    estado: EstadoSimulacao | None = None,
) -> None:
    x, y, w, h = b.x, b.y, b.w, b.h
    x0 = x + w - 40  # o símbolo ocupa os 40 pt da direita; à esquerda, o nome da entrada
    canal_x = x + w - 12
    placa = x0 + 13
    canal = x0 + 18
    p.setBrush(Qt.BrushStyle.NoBrush)
    pmos = b.simbolo == "pmos"
    porta = b.pino("G")
    fim_porta = placa - (7 if pmos else 0)
    p.drawLine(QPointF(x, y + h / 2), QPointF(fim_porta, y + h / 2))
    if pmos:
        p.drawEllipse(QPointF(placa - 3.5, y + h / 2), 3.5, 3.5)
    p.drawLine(QPointF(placa, y + h * 0.22), QPointF(placa, y + h * 0.78))
    if conduz is not None:
        # conduzindo: canal grosso na cor do 1; cortado: canal tracejado e apagado
        cores = _cores()
        cor_canal = cores.nivel1 if conduz else cores.tenue
        caneta = _caneta(cor_canal, 3.2 if conduz else 1.2)
        if not conduz:
            caneta.setStyle(Qt.PenStyle.DashLine)
        p.save()
        p.setPen(caneta)
        p.drawLine(QPointF(canal, y + h * 0.16), QPointF(canal, y + h * 0.84))
        p.restore()
    else:
        p.drawLine(QPointF(canal, y + h * 0.16), QPointF(canal, y + h * 0.84))
    for lado, yy in (("n", y + h * 0.24), ("s", y + h * 0.76)):
        p.drawLine(QPointF(canal, yy), QPointF(canal_x, yy))
        p.drawLine(QPointF(canal_x, yy), QPointF(canal_x, y if lado == "n" else y + h))
    # seta na fonte: nMOS saindo do canal (fonte embaixo), pMOS entrando (fonte em cima)
    yy = y + h * (0.24 if pmos else 0.76)
    meio = (canal + canal_x) / 2
    dx = -4 if pmos else 4
    p.setBrush(cor)
    p.drawPolygon(QPolygonF([QPointF(meio + dx, yy), QPointF(meio - dx, yy - 3.2),
                             QPointF(meio - dx, yy + 3.2)]))  # fmt: skip
    if com_texto:
        f = QFont(p.font())
        if porta.rede_externa:
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            p.setPen(_cores().destaque_texto if cor != _cores().acento else cor)
            texto = porta.rede_externa
            if estado is not None and estado.transistores is not None:
                v = estado.transistores[0].get(porta.rede_externa, "?")
                texto += f"={v}" if v != "?" else ""
            alinhamento = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
            p.drawText(QRectF(x - 2, y + h / 2 - 14, x0 - x + 14, 12), alinhamento, texto)
        f.setPixelSize(8)
        f.setBold(False)
        p.setFont(f)
        p.setPen(cor)
        w_l = f"{b.detalhes.get('W', '')}/{b.detalhes.get('L', '')}".replace(" µm", "")
        p.drawText(QPointF(canal_x + 4, y + h / 2 + 3), w_l)


def _rotulos_internos(p: QPainter, b: Bloco, cor: QColor) -> None:
    s = b.simbolo
    f = QFont(p.font())
    f.setPixelSize(9)
    p.setFont(f)
    tenue = QColor(cor)
    tenue.setAlphaF(0.75)
    if s in CAIXAS_COM_PINOS:
        p.setPen(tenue)
        for pino in b.pinos:
            px, py = b.x + pino.x, b.y + pino.y
            if pino.lado == "w":
                eh_relogio = s in {"registrador", "latch"} and pino.nome.upper() in {
                    "CLK", "C", "CLK_N", "GATE", "GATE_N", "CK"}  # fmt: skip
                if eh_relogio:
                    p.setPen(_caneta(cor, 1.2))
                    p.drawPolyline(QPolygonF([QPointF(px, py - 5), QPointF(px + 7, py),
                                              QPointF(px, py + 5)]))  # fmt: skip
                    p.setPen(tenue)
                    p.drawText(QPointF(px + 9, py + 3), pino.nome)
                else:
                    p.drawText(QPointF(px + 4, py + 3), pino.nome)
            elif pino.lado == "e":
                largura = QFontMetricsF(f).horizontalAdvance(pino.nome)
                p.drawText(QPointF(px - largura - 4, py + 3), pino.nome)
            elif pino.lado == "s":
                p.drawText(QPointF(px - 4, py - 4), pino.nome)
        titulo = b.rotulo
        if s == "registrador":
            titulo = "FF" if b.largura_bits <= 1 else f"FF ×{b.largura_bits}"
        elif s == "latch":
            titulo = "latch" if b.largura_bits <= 1 else f"latch ×{b.largura_bits}"
        _texto_centro(p, QRectF(b.x, b.y + b.h - 15, b.w, 12) if s in {"registrador", "latch"}
                      else QRectF(b.x, b.y, b.w, b.h), titulo, cor, 10, negrito=True)  # fmt: skip
    elif s == "mux":
        p.setPen(tenue)
        for pino in b.pinos:
            px, py = b.x + pino.x, b.y + pino.y
            if pino.lado == "w":
                p.drawText(QPointF(px + 4, py + 3), NOMES_MUX.get(pino.nome, pino.nome))
            elif pino.lado == "s":
                p.drawText(QPointF(px + 3, py - 6), pino.nome)
    elif s in {"and", "or", "xor", "nand", "nor", "xnor", "not", "buf", "tribuf"} and b.rotulo:
        # nome da célula (nand2, xor2…) ou do operador de redução, embaixo do símbolo
        p.setPen(tenue)
        p.drawText(QRectF(b.x - 10, b.y + b.h + 1, b.w + 20, 11),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, b.rotulo)  # fmt: skip
