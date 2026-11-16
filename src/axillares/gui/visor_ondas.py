"""VisorOndas: as formas de onda desenhadas dentro do app, na paleta Phareon.

Quem lê o VCD/FST é o pywellen (motor/ondas.py); aqui só se desenha. Uma linha por sinal: o nome e
o valor no instante do cursor à esquerda; a onda à direita — 1 bit como degrau, barramento como
"hexágonos" com o valor dentro, X em vermelho e Z em amarelo. Em testes cocotb, uma faixa no topo
mostra o trecho de cada teste (verde passou, vermelho falhou).

Mouse: clique põe o cursor e escolhe a linha; arrastar move no tempo; Ctrl+roda dá zoom no
ponto do mouse; roda rola as linhas (ou move no tempo, se todas couberem). Teclado: + e −, F
(ajustar), ← e → (mudança anterior/seguinte do sinal escolhido).
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from axillares.gui import tema as t
from axillares.gui.tema import Papel
from axillares.motor.ondas import Onda, desconhecido, formatar

LARGURA_NOMES = 230
ALTURAS = {"compacta": 26, "normal": 36, "grande": 52}
ALTURA_REGUA = 30
ALTURA_FAIXAS = 24
MARGEM = 6
PASSOS_REGUA = (1, 2, 5)
UNIDADES = (("s", 1e12), ("ms", 1e9), ("µs", 1e6), ("ns", 1e3), ("ps", 1.0), ("fs", 1e-3))


@dataclass(frozen=True)
class Faixa:
    """Um trecho do tempo com nome e veredito — um teste cocotb."""

    inicio: float
    fim: float
    nome: str
    passou: bool


def texto_tempo(ps: float) -> str:
    """1234567 ps → '1,23 µs' (unidade mais legível)."""
    if ps == 0:
        return "0"
    for nome, fator in UNIDADES:
        if abs(ps) >= fator:
            valor = ps / fator
            casas = 0 if valor == int(valor) else (1 if valor >= 10 else 2)
            return f"{valor:.{casas}f}".replace(".", ",") + f" {nome}"
    return f"{ps:g} ps"


def passo_bonito(alvo: float) -> float:
    """O menor 1·10ⁿ, 2·10ⁿ ou 5·10ⁿ que seja ≥ alvo."""
    if alvo <= 0:
        return 1.0
    expoente = math.floor(math.log10(alvo))
    for m in PASSOS_REGUA:
        passo = m * 10**expoente
        if passo >= alvo:
            return passo
    return 10 ** (expoente + 1)


class VisorOndas(QWidget):
    cursor_mudou = Signal(object)
    """Tempo do cursor (unidades da onda) ou None."""
    linha_escolhida = Signal(object)
    menu_da_linha = Signal(str, object)
    """Botão direito no nome de um sinal: (nome completo, posição global)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(420, 200)
        self.onda: Onda | None = None
        self.linhas: list[str] = []
        self.base = "hex"
        self.faixas: list[Faixa] = []
        self.t0 = 0.0
        self.por_pixel = 1.0
        self.cursor: int | None = None
        self.cursor_b: int | None = None
        """Segundo cursor (Shift+clique ou botão direito): mede o intervalo até o primeiro."""
        self.altura = ALTURAS["normal"]
        self.modos: dict[str, str] = {}
        """Por sinal: "digital" ou "analogico" (barramento desenhado como curva)."""
        self.cores: dict[str, int] = {}
        """Por sinal: índice na série de cores do tema."""
        self.escolhida: int | None = None
        self.rolagem = 0
        self._arrasto: tuple[float, float] | None = None
        self._ajustado = True
        """Enquanto o usuário não der zoom nem arrastar, a onda acompanha a largura da tela."""
        self._arrastou = False
        self._fonte = t.fonte(Papel.MONO)
        self._fonte_pequena = t.fonte(Papel.ETIQUETA)
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.update()

    # --- dados -------------------------------------------------------------------------------

    def definir(self, onda: Onda | None, linhas: list[str], faixas: list[Faixa] | None = None):
        self.onda = onda
        self.linhas = list(linhas)
        self.faixas = list(faixas or [])
        self.cursor = None
        self.cursor_b = None
        self.cores = {}
        self.modos = {}
        self.escolhida = 0 if linhas else None
        self.rolagem = 0
        self.ajustar()
        self.cursor_mudou.emit(None)

    def definir_linhas(self, linhas: list[str]) -> None:
        self.linhas = list(linhas)
        if self.escolhida is not None and self.escolhida >= len(self.linhas):
            self.escolhida = len(self.linhas) - 1 if self.linhas else None
        self._limitar_rolagem()
        self.update()

    def definir_altura(self, nome: str) -> None:
        self.altura = ALTURAS.get(nome, ALTURAS["normal"])
        self._limitar_rolagem()
        self.update()

    def cor_de(self, nome: str):
        if nome not in self.cores:
            self.cores[nome] = len(self.cores)
        return t.paleta().serie(self.cores[nome])

    def definir_modo(self, nome: str, modo: str) -> None:
        self.modos[nome] = modo
        self.update()

    def definir_cor(self, nome: str, indice: int) -> None:
        self.cores[nome] = indice
        self.update()

    def definir_base(self, base: str) -> None:
        self.base = base
        self.update()

    # --- geometria ---------------------------------------------------------------------------

    @property
    def _topo_linhas(self) -> int:
        return ALTURA_REGUA + (ALTURA_FAIXAS if self.faixas else 0)

    @property
    def _largura_onda(self) -> int:
        return max(1, self.width() - LARGURA_NOMES)

    @property
    def fim(self) -> int:
        return self.onda.fim if self.onda else 0

    def x_de(self, tempo: float) -> float:
        return LARGURA_NOMES + (tempo - self.t0) / self.por_pixel

    def tempo_de(self, x: float) -> float:
        return self.t0 + (x - LARGURA_NOMES) * self.por_pixel

    def ajustar(self) -> None:
        """Toda a simulação cabe na largura."""
        fim = max(self.fim, 1)
        self.t0 = 0.0
        self.por_pixel = fim * 1.04 / self._largura_onda
        self._ajustado = True
        self.update()

    def zoom(self, fator: float, ancora_x: float | None = None) -> None:
        if ancora_x is None:
            ancora_x = LARGURA_NOMES + self._largura_onda / 2
        ancora = self.tempo_de(ancora_x)
        self._ajustado = False
        minimo = 1e-3  # 1/1000 de unidade por pixel: zoom bem fundo
        maximo = max(self.fim, 1) * 4 / self._largura_onda
        self.por_pixel = min(max(self.por_pixel / fator, minimo), maximo)
        self.t0 = ancora - (ancora_x - LARGURA_NOMES) * self.por_pixel
        self._limitar_t0()
        self.update()

    def _limitar_t0(self) -> None:
        visivel = self._largura_onda * self.por_pixel
        self.t0 = min(max(self.t0, -visivel * 0.5), max(self.fim, 1) - visivel * 0.5)

    def _limitar_rolagem(self) -> None:
        cabem = max(1, (self.height() - self._topo_linhas) // self.altura)
        self.rolagem = max(0, min(self.rolagem, len(self.linhas) - cabem))

    def resizeEvent(self, evento) -> None:
        self._limitar_rolagem()
        if self._ajustado:
            self.ajustar()
        super().resizeEvent(evento)

    def _nomes_visiveis(self) -> dict[str, str]:
        """Nome curto de cada linha; se dois se repetem (tb.q e tb.dut.q), mostra o caminho."""
        if self.onda is None:
            return {}
        por_nome = {s.nome_completo: s for s in self.onda.sinais}
        curtos = [por_nome[x].nome for x in self.linhas if x in por_nome]
        saida = {}
        for x in self.linhas:
            s = por_nome.get(x)
            if s is None:
                continue
            repetido = curtos.count(s.nome) > 1
            saida[x] = x.partition(".")[2] or x if repetido else s.nome
        return saida

    # --- desenho -----------------------------------------------------------------------------

    def paintEvent(self, _evento) -> None:
        pal = t.paleta()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), pal.qcolor("fundo"))
        p.fillRect(QRectF(0, 0, LARGURA_NOMES, self.height()), pal.qcolor("fundo_2"))
        if self.onda is None:
            p.end()
            return
        self._regua(p, pal)
        if self.faixas:
            self._faixas(p, pal)
        topo = self._topo_linhas
        self._nomes = self._nomes_visiveis()
        p.setClipRect(QRectF(0, topo, self.width(), self.height() - topo))
        for i in range(self.rolagem, len(self.linhas)):
            y = topo + (i - self.rolagem) * self.altura
            if y > self.height():
                break
            self._linha(p, pal, i, y)
        p.setClipping(False)
        p.setPen(QPen(pal.qcolor("linha_media"), 1))
        p.drawLine(QPointF(LARGURA_NOMES, 0), QPointF(LARGURA_NOMES, self.height()))
        self._cursor(p, pal)
        p.end()

    def _regua(self, p: QPainter, pal) -> None:
        onda = self.onda
        assert onda is not None
        p.fillRect(QRectF(LARGURA_NOMES, 0, self._largura_onda, ALTURA_REGUA),
                   pal.qcolor("fundo_2"))  # fmt: skip
        p.setFont(self._fonte_pequena)
        passo = passo_bonito(110 * self.por_pixel)
        inicio = math.floor(max(self.t0, 0) / passo) * passo
        x_fim = self.width()
        tempo = inicio
        while True:
            x = self.x_de(tempo)
            if x > x_fim:
                break
            if x >= LARGURA_NOMES:
                p.setPen(QPen(pal.qcolor("linha"), 1))
                p.drawLine(QPointF(x, ALTURA_REGUA - 7), QPointF(x, self.height()))
                p.setPen(pal.qcolor("tinta_3"))
                rotulo_ = texto_tempo(onda.em_ps(tempo))
                p.drawText(QPointF(x + 4, ALTURA_REGUA - 11), rotulo_)
            tempo += passo
            if passo <= 0:
                break
        p.setPen(QPen(pal.qcolor("linha_media"), 1))
        p.drawLine(QPointF(0, ALTURA_REGUA), QPointF(self.width(), ALTURA_REGUA))
        p.setPen(pal.qcolor("tinta_3"))
        unidade = f"TEMPO · escala {onda.fator} {onda.unidade}"
        p.drawText(QPointF(14, ALTURA_REGUA - 11), unidade.upper())

    def _faixas(self, p: QPainter, pal) -> None:
        y = ALTURA_REGUA + 3
        altura = ALTURA_FAIXAS - 6
        p.setFont(self._fonte_pequena)
        p.setPen(pal.qcolor("tinta_3"))
        p.drawText(QPointF(14, y + altura - 5), "TESTES")
        for f in self.faixas:
            x0, x1 = max(self.x_de(f.inicio), LARGURA_NOMES), min(self.x_de(f.fim), self.width())
            if x1 <= x0:
                continue
            cor = pal.qcolor("ok" if f.passou else "falha")
            fundo = QColor(cor)
            fundo.setAlpha(46)
            caixa = QRectF(x0 + 1, y, x1 - x0 - 2, altura)
            p.setPen(QPen(cor, 1))
            p.setBrush(fundo)
            p.drawRoundedRect(caixa, 3, 3)
            p.setPen(cor)
            texto = ("✓ " if f.passou else "✕ ") + f.nome
            elidido = QFontMetrics(self._fonte_pequena).elidedText(
                texto, Qt.TextElideMode.ElideRight, int(caixa.width()) - 8
            )
            p.drawText(caixa.adjusted(6, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter, elidido)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _linha(self, p: QPainter, pal, i: int, y: float) -> None:
        onda = self.onda
        assert onda is not None
        nome = self.linhas[i]
        sinal = next((s for s in onda.sinais if s.nome_completo == nome), None)
        if sinal is None:
            return
        if i == self.escolhida:
            destaque = QColor(pal.qcolor("acento"))
            destaque.setAlpha(22)
            p.fillRect(QRectF(0, y, self.width(), self.altura), destaque)
            p.fillRect(QRectF(0, y, 2, self.altura), pal.qcolor("acento"))
        p.setPen(QPen(pal.qcolor("linha"), 1))
        p.drawLine(QPointF(0, y + self.altura), QPointF(self.width(), y + self.altura))

        cor_sinal = self.cor_de(nome)
        p.fillRect(QRectF(5, y + 8, 4, self.altura - 16), cor_sinal)
        # nome e valor no cursor
        p.setFont(self._fonte)
        p.setPen(pal.qcolor("tinta"))
        largura = f"[{sinal.largura - 1}:0]" if sinal.largura > 1 else ""
        metrica = QFontMetrics(self._fonte)
        valor_txt = ""
        if self.cursor is not None:
            valor_txt = formatar(onda.valor_em(nome, self.cursor), sinal.largura, self.base)
        espaco_nome = LARGURA_NOMES - 26 - (metrica.horizontalAdvance(valor_txt) + 10)
        nome_visivel = self._nomes.get(nome, sinal.nome)
        texto_nome = metrica.elidedText(nome_visivel + largura, Qt.TextElideMode.ElideLeft,
                                        max(40, espaco_nome))  # fmt: skip
        p.drawText(QRectF(14, y, LARGURA_NOMES - 20, self.altura),
                   Qt.AlignmentFlag.AlignVCenter, texto_nome)  # fmt: skip
        if valor_txt:
            p.setPen(cor_sinal)
            direita = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            p.drawText(QRectF(14, y, LARGURA_NOMES - 26, self.altura), direita, valor_txt)

        mudancas = onda.mudancas(nome)
        if not mudancas:
            return
        t_ini, t_fim = self.tempo_de(LARGURA_NOMES), self.tempo_de(self.width())
        tempos = [m[0] for m in mudancas]
        k = max(0, bisect.bisect_right(tempos, t_ini) - 1)
        alto, baixo = y + MARGEM + 2, y + self.altura - MARGEM - 2
        espessura = 2.0 if self.altura >= ALTURAS["normal"] else 1.6
        if sinal.largura > 1 and self.modos.get(nome) == "analogico":
            p.setClipRect(QRectF(LARGURA_NOMES, y, self._largura_onda, self.altura))
            self._analogico(p, pal, mudancas, k, t_fim, alto, baixo, cor_sinal, espessura)
            p.setClipping(False)
            return
        meio = (alto + baixo) / 2
        fim_onda = max(self.fim, tempos[-1])
        p.setClipRect(QRectF(LARGURA_NOMES, y, self._largura_onda, self.altura))
        anterior_y: float | None = None
        while k < len(mudancas):
            tempo, valor = mudancas[k]
            if tempo > t_fim:
                break
            prox = mudancas[k + 1][0] if k + 1 < len(mudancas) else fim_onda
            x0, x1 = self.x_de(tempo), self.x_de(prox)
            estranho = desconhecido(valor)
            if sinal.largura == 1:
                if estranho:
                    cor = pal.qcolor("falha" if estranho == "x" else "aviso")
                    if estranho == "x":
                        suave = QColor(cor)
                        suave.setAlpha(40)
                        p.fillRect(QRectF(x0, alto, x1 - x0, baixo - alto), suave)
                    p.setPen(QPen(cor, espessura))
                    p.drawLine(QPointF(x0, meio), QPointF(x1, meio))
                    y_atual = meio
                else:
                    y_atual = alto if valor else baixo
                    if valor:
                        preench = QColor(cor_sinal)
                        preench.setAlpha(34)
                        p.fillRect(QRectF(x0, alto, x1 - x0, baixo - alto), preench)
                    p.setPen(QPen(cor_sinal, espessura))
                    p.drawLine(QPointF(x0, y_atual), QPointF(x1, y_atual))
                if anterior_y is not None and anterior_y != y_atual:
                    p.drawLine(QPointF(x0, anterior_y), QPointF(x0, y_atual))
                anterior_y = y_atual
            else:
                self._barramento(p, pal, x0, x1, alto, baixo, valor, sinal.largura, estranho,
                                 cor_sinal)  # fmt: skip
            k += 1
        p.setClipping(False)

    def _analogico(self, p, pal, mudancas, k, t_fim, alto, baixo, cor, espessura) -> None:
        """Barramento como curva em degraus: a altura é o número (como um osciloscópio)."""
        numeros = [v for _t, v in mudancas if isinstance(v, int)]
        if not numeros:
            return
        minimo, maximo = min(numeros), max(numeros)
        faixa = max(maximo - minimo, 1)
        fim_onda = max(self.fim, mudancas[-1][0])
        caminho = QPainterPath()
        preenchimento = QPainterPath()
        anterior = None
        inicio_x = None
        while k < len(mudancas):
            tempo, valor = mudancas[k]
            if tempo > t_fim:
                break
            prox = mudancas[k + 1][0] if k + 1 < len(mudancas) else fim_onda
            x0, x1 = self.x_de(tempo), self.x_de(prox)
            if isinstance(valor, int):
                yv = baixo - (valor - minimo) / faixa * (baixo - alto)
                if anterior is None:
                    caminho.moveTo(x0, yv)
                    preenchimento.moveTo(x0, baixo)
                    preenchimento.lineTo(x0, yv)
                    inicio_x = x0
                else:
                    caminho.lineTo(x0, yv)
                    preenchimento.lineTo(x0, yv)
                caminho.lineTo(x1, yv)
                preenchimento.lineTo(x1, yv)
                anterior = (x1, yv)
            else:  # X/Z: a curva se interrompe
                if anterior is not None:
                    preenchimento.lineTo(anterior[0], baixo)
                anterior = None
                cor_x = pal.qcolor("falha")
                cor_x.setAlpha(50)
                p.fillRect(QRectF(x0, alto, x1 - x0, baixo - alto), cor_x)
            k += 1
        if anterior is not None and inicio_x is not None:
            preenchimento.lineTo(anterior[0], baixo)
            preenchimento.closeSubpath()
        suave = QColor(cor)
        suave.setAlpha(36)
        p.fillPath(preenchimento, suave)
        p.setPen(QPen(cor, espessura))
        p.drawPath(caminho)
        p.setFont(self._fonte_pequena)
        p.setPen(pal.qcolor("tinta_3"))
        x = LARGURA_NOMES + 4
        p.drawText(QPointF(x, alto + 9), formatar(maximo, 32, "dec"))
        p.drawText(QPointF(x, baixo - 1), formatar(minimo, 32, "dec"))

    def _barramento(self, p, pal, x0, x1, alto, baixo, valor, largura, estranho,
                    cor_sinal=None) -> None:  # fmt: skip
        meio = (alto + baixo) / 2
        bico = min(4.0, max(0.0, (x1 - x0) / 3))
        forma = QPolygonF([QPointF(x0, meio), QPointF(x0 + bico, alto), QPointF(x1 - bico, alto),
                           QPointF(x1, meio), QPointF(x1 - bico, baixo),
                           QPointF(x0 + bico, baixo)])  # fmt: skip
        caminho = QPainterPath()
        caminho.addPolygon(forma)
        caminho.closeSubpath()
        if estranho:
            cor = pal.qcolor("falha" if estranho == "x" else "aviso")
            fundo = QColor(cor)
            fundo.setAlpha(44)
        else:
            cor = cor_sinal if cor_sinal is not None else pal.qcolor("tinta_2")
            fundo = QColor(cor)
            fundo.setAlpha(30)
        p.fillPath(caminho, fundo)
        p.setPen(QPen(cor, 1.4))
        p.drawPath(caminho)
        if x1 - x0 > 18:
            texto = formatar(valor, largura, self.base)
            metrica = QFontMetrics(self._fonte_pequena)
            visivel = QRectF(max(x0, LARGURA_NOMES) + bico + 2, alto,
                             min(x1, self.width()) - max(x0, LARGURA_NOMES) - 2 * bico - 4,
                             baixo - alto)  # fmt: skip
            if visivel.width() > 10:
                p.setFont(self._fonte_pequena)
                p.setPen(pal.qcolor("tinta") if not estranho else cor)
                elidido = metrica.elidedText(texto, Qt.TextElideMode.ElideRight,
                                             int(visivel.width()))  # fmt: skip
                p.drawText(visivel, Qt.AlignmentFlag.AlignCenter, elidido)

    def _cursor(self, p: QPainter, pal) -> None:
        if self.onda is None:
            return
        if self.cursor is not None and self.cursor_b is not None:
            xa, xb = self.x_de(self.cursor), self.x_de(self.cursor_b)
            faixa = QColor(pal.serie(1))
            faixa.setAlpha(28)
            esquerda, direita = max(min(xa, xb), LARGURA_NOMES), min(max(xa, xb), self.width())
            if direita > esquerda:
                p.fillRect(QRectF(esquerda, ALTURA_REGUA, direita - esquerda,
                                  self.height() - ALTURA_REGUA), faixa)  # fmt: skip
        if self.cursor_b is not None:
            self._linha_cursor(p, pal, self.cursor_b, pal.serie(1), "B ")
        if self.cursor is not None:
            self._linha_cursor(p, pal, self.cursor, pal.qcolor("acento"), "")

    def _linha_cursor(self, p: QPainter, pal, tempo: int, cor, prefixo: str) -> None:
        assert self.onda is not None
        x = self.x_de(tempo)
        if x < LARGURA_NOMES or x > self.width():
            return
        p.setPen(QPen(cor, 1.4, Qt.PenStyle.DashLine if prefixo else Qt.PenStyle.SolidLine))
        p.drawLine(QPointF(x, ALTURA_REGUA), QPointF(x, self.height()))
        texto = prefixo + texto_tempo(self.onda.em_ps(tempo))
        p.setFont(self._fonte_pequena)
        largura = QFontMetrics(self._fonte_pequena).horizontalAdvance(texto) + 14
        caixa = QRectF(min(x - largura / 2, self.width() - largura - 2), 5, largura, 18)
        caixa.moveLeft(max(caixa.left(), LARGURA_NOMES + 2))
        p.setBrush(cor)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(caixa, 9, 9)
        p.setPen(pal.qcolor("sobre_acento"))
        p.drawText(caixa, Qt.AlignmentFlag.AlignCenter, texto)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def definir_cursor_b(self, tempo: float | None) -> None:
        self.cursor_b = None if tempo is None else int(max(0, round(tempo)))
        self.cursor_mudou.emit(self.cursor)
        self.update()

    # --- interação ---------------------------------------------------------------------------

    def _linha_em(self, y: float) -> int | None:
        if y < self._topo_linhas:
            return None
        i = self.rolagem + int((y - self._topo_linhas) // self.altura)
        return i if 0 <= i < len(self.linhas) else None

    def definir_cursor(self, tempo: float | None) -> None:
        self.cursor = None if tempo is None else int(max(0, round(tempo)))
        self.cursor_mudou.emit(self.cursor)
        self.update()

    def mousePressEvent(self, evento) -> None:
        x = evento.position().x()
        segundo = evento.button() == Qt.MouseButton.RightButton or (
            evento.button() == Qt.MouseButton.LeftButton
            and evento.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if segundo and x > LARGURA_NOMES:
            self.definir_cursor_b(self.tempo_de(x))
            self._arrasto = None
            return
        if evento.button() == Qt.MouseButton.RightButton and x <= LARGURA_NOMES:
            linha = self._linha_em(evento.position().y())
            if linha is not None:
                self.menu_da_linha.emit(self.linhas[linha], evento.globalPosition().toPoint())
            return
        if evento.button() == Qt.MouseButton.LeftButton:
            self._arrasto = (evento.position().x(), self.t0)
            self._arrastou = False
            linha = self._linha_em(evento.position().y())
            if linha is not None:
                self.escolhida = linha
                self.linha_escolhida.emit(self.linhas[linha])
                self.update()

    def mouseMoveEvent(self, evento) -> None:
        if self._arrasto is not None and evento.buttons() & Qt.MouseButton.LeftButton:
            x0, t0 = self._arrasto
            dx = evento.position().x() - x0
            if abs(dx) > 4:
                self._arrastou = True
            if self._arrastou:
                self._ajustado = False
                self.t0 = t0 - dx * self.por_pixel
                self._limitar_t0()
                self.update()

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            if not self._arrastou and evento.position().x() > LARGURA_NOMES:
                self.definir_cursor(self.tempo_de(evento.position().x()))
            self._arrasto = None

    def wheelEvent(self, evento) -> None:
        dy = evento.angleDelta().y()
        if not dy:
            return
        modificadores = evento.modifiers()
        cabem = (self.height() - self._topo_linhas) // self.altura
        if modificadores & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.25 if dy > 0 else 0.8, evento.position().x())
        elif modificadores & Qt.KeyboardModifier.ShiftModifier or len(self.linhas) <= cabem:
            self.t0 -= dy / 120 * 60 * self.por_pixel
            self._limitar_t0()
            self.update()
        else:
            self.rolagem -= 1 if dy > 0 else -1
            self._limitar_rolagem()
            self.update()

    def keyPressEvent(self, evento) -> None:
        tecla = evento.key()
        if tecla in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(1.5)
        elif tecla == Qt.Key.Key_Minus:
            self.zoom(1 / 1.5)
        elif tecla == Qt.Key.Key_F:
            self.ajustar()
        elif tecla == Qt.Key.Key_Escape:
            self.definir_cursor_b(None)
        elif tecla in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.pular(tecla == Qt.Key.Key_Right)
        elif tecla in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.linhas:
            passo = 1 if tecla == Qt.Key.Key_Down else -1
            self.escolhida = max(0, min(len(self.linhas) - 1, (self.escolhida or 0) + passo))
            self.linha_escolhida.emit(self.linhas[self.escolhida])
            self.update()
        else:
            super().keyPressEvent(evento)

    def pular(self, adiante: bool) -> None:
        """Leva o cursor à mudança seguinte (ou anterior) do sinal escolhido."""
        if self.onda is None or self.escolhida is None or not self.linhas:
            return
        tempos = [m[0] for m in self.onda.mudancas(self.linhas[self.escolhida])]
        atual = self.cursor if self.cursor is not None else (-1 if adiante else self.fim + 1)
        if adiante:
            i = bisect.bisect_right(tempos, atual)
            alvo = tempos[i] if i < len(tempos) else None
        else:
            i = bisect.bisect_left(tempos, atual) - 1
            alvo = tempos[i] if i >= 0 else None
        if alvo is None:
            return
        self.definir_cursor(alvo)
        x = self.x_de(alvo)
        if not LARGURA_NOMES <= x <= self.width():
            self.t0 = alvo - self._largura_onda * self.por_pixel / 2
            self._limitar_t0()
            self.update()
