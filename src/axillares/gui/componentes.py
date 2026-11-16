"""Peças visuais reutilizáveis. Nenhuma cor literal: tudo vem de `tema`."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
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


class Rotulo(QLabel):
    """QLabel que aplica a caixa alta do papel ao texto (preservando unidades), em vez de
    deixar a fonte capitalizar — o que transformaria "µm" em "ΜM"."""

    def __init__(self, texto: str, papel: Papel) -> None:
        super().__init__()
        self._caixa_alta = papel.value.caixa_alta
        f = t.fonte(papel)
        f.setCapitalization(f.Capitalization.MixedCase)
        self.setFont(f)
        self.setText(texto)

    def setText(self, texto: str) -> None:
        super().setText(t.caixa_alta(texto) if self._caixa_alta and "<" not in texto else texto)

    # Responsividade: um QLabel com quebra de linha informa uma altura mínima que ignora a quebra,
    # e o layout o espreme até o texto sumir atrás do vizinho. Aqui a altura mínima acompanha a
    # largura real — o layout cresce (ou rola) em vez de cortar o texto.
    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        if self.wordWrap():
            necessaria = self.heightForWidth(self.width())
            if necessaria > 0 and necessaria != self.minimumHeight():
                self.setMinimumHeight(necessaria)
                self.updateGeometry()


def rotulo(
    texto: str = "", papel: Papel = Papel.CORPO, tom: str | None = None, rico: bool = False
) -> QLabel:
    r = Rotulo(texto, papel)
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
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.update()

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
        self.numero = rotulo(f"{numero} /", Papel.NUMERO_SECAO, "acento")
        topo.addWidget(self.numero)
        topo.addWidget(rotulo(titulo, Papel.NUMERO_SECAO, "2"))
        topo.addStretch(1)
        self.apoio = rotulo(apoio, Papel.ROTULO, "3")
        self.apoio.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.apoio.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        topo.addWidget(self.apoio, 1)
        lay.addLayout(topo)
        lay.addWidget(regua())

    def definir_numero(self, numero: str) -> None:
        self.numero.setText(f"{numero} /")


class Pilula(QWidget):
    """Situação de uma verificação: contorno fino, ponto colorido, texto mono."""

    def __init__(self, texto: str = "", token: str = "tinta_3") -> None:
        super().__init__()
        self._texto = t.caixa_alta(texto)
        self._token = token
        self._fonte = t.fonte(Papel.ETIQUETA)
        self._fonte.setCapitalization(self._fonte.Capitalization.MixedCase)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.update()

    def definir(self, texto: str, token: str) -> None:
        self._texto, self._token = t.caixa_alta(texto), token
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        from PySide6.QtGui import QFontMetrics

        largura = QFontMetrics(self._fonte).horizontalAdvance(self._texto)
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
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.update()

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
        self.setMinimumWidth(150)
        self._ultimo: tuple[str, str, str] = ("—", "", "")
        t.tema().mudou.connect(self._tema_mudou)

    def _tema_mudou(self, _paleta: object) -> None:
        self.definir(*self._ultimo)

    def definir(self, valor: str, unidade: str = "", nota: str = "") -> None:
        self._ultimo = (valor, unidade, nota)
        texto = valor
        if unidade:
            texto += "&#8202;" + t.serifa(unidade, t.paleta().tinta_2, 20)
        self._valor.setText(texto)
        self._nota.setText(nota)


# --- tabela e cabeçalho -----------------------------------------------------------------------


class _LinhaClicavel(QFrame):
    def __init__(self, ao_clicar) -> None:
        super().__init__()
        self._ao_clicar = ao_clicar
        self.setProperty("tipo", "linha-tabela")
        if ao_clicar:
            self.setProperty("selecionavel", "sim")
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, evento) -> None:
        if self._ao_clicar and evento.button() == Qt.MouseButton.LeftButton:
            self._ao_clicar()
        super().mouseReleaseEvent(evento)


class Tabela(QWidget):
    """Tabela leve: cabeçalho mono em caixa alta, linhas separadas por hairline.

    colunas: [(título, peso, alinhamento 'e'|'d')]. Células: texto (fonte por coluna) ou widget.
    """

    def __init__(self, colunas: list[tuple[str, int, str]], papeis: list[Papel] | None = None):
        super().__init__()
        self.colunas = colunas
        self.papeis = papeis or [Papel.CORPO] * len(colunas)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        cab = QWidget()
        g = QGridLayout(cab)
        g.setContentsMargins(Espaco.S, 0, Espaco.S, Espaco.S)
        g.setHorizontalSpacing(Espaco.M)
        for i, (titulo, peso, alin) in enumerate(colunas):
            r = rotulo(titulo, Papel.ROTULO, "3")
            r.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            if alin == "d":
                r.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            g.addWidget(r, 0, i)
            g.setColumnStretch(i, peso)
        lay.addWidget(cab)
        self._corpo = quadro("tabela")
        self._linhas = QVBoxLayout(self._corpo)
        self._linhas.setContentsMargins(0, 0, 0, 0)
        self._linhas.setSpacing(0)
        lay.addWidget(self._corpo)
        self.vazio = rotulo("", Papel.PEQUENO, "2")
        self.vazio.setContentsMargins(Espaco.S, Espaco.M, 0, 0)
        lay.addWidget(self.vazio)

    def limpar(self) -> None:
        while self._linhas.count():
            item = self._linhas.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def adicionar(self, celulas: list, ao_clicar=None, tons: list[str | None] | None = None):
        linha = _LinhaClicavel(ao_clicar)
        g = QGridLayout(linha)
        g.setContentsMargins(Espaco.S, Espaco.M - 5, Espaco.S, Espaco.M - 5)
        g.setHorizontalSpacing(Espaco.M)
        for i, celula in enumerate(celulas):
            _t, peso, alin = self.colunas[i]
            if isinstance(celula, QWidget):
                w = celula
            else:
                tom = tons[i] if tons else None
                w = rotulo(str(celula), self.papeis[i], tom)
                w.setTextFormat(
                    Qt.TextFormat.RichText if "<" in str(celula) else Qt.TextFormat.PlainText
                )
            alinhamento = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignRight if alin == "d" else Qt.AlignmentFlag.AlignLeft
            )
            if isinstance(w, QLabel):
                # a largura vem só do peso da coluna: as linhas ficam alinhadas entre si
                w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                w.setAlignment(alinhamento)
                g.addWidget(w, 0, i)
            else:
                g.addWidget(w, 0, i, alinhamento)
            g.setColumnStretch(i, peso)
            g.setColumnMinimumWidth(i, 0)
        self._linhas.addWidget(linha)
        self.vazio.hide()
        return linha

    def mostrar_vazio(self, texto: str) -> None:
        self.limpar()
        self.vazio.setText(texto)
        self.vazio.show()


def cabecalho_tela(eyebrow: str, titulo: str, lead: str = "") -> tuple[QVBoxLayout, QLabel]:
    """Eyebrow + título display (+ lead). Devolve o layout e o rótulo do título."""
    lay = QVBoxLayout()
    lay.setSpacing(Espaco.M - 2)
    lay.addWidget(Eyebrow(eyebrow))
    t_ = rotulo(titulo, Papel.HERO, rico=True)
    t_.setWordWrap(True)
    lay.addWidget(t_)
    if lead:
        r = rotulo(lead, Papel.LEAD, "2")
        r.setWordWrap(True)
        r.setMaximumWidth(620)
        lay.addWidget(r)
    return lay, t_


def tela_rolavel(conteudo: QWidget) -> QWidget:
    """Envolve o conteúdo de uma tela com rolagem vertical e as margens padrão."""
    from PySide6.QtWidgets import QScrollArea

    rolagem = QScrollArea()
    rolagem.setWidgetResizable(True)
    rolagem.setFrameShape(QFrame.Shape.NoFrame)
    rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rolagem.setWidget(conteudo)
    return rolagem


def layout_de_tela(w: QWidget) -> QVBoxLayout:
    lay = QVBoxLayout(w)
    lay.setContentsMargins(Espaco.MARGEM, Espaco.XL + 8, Espaco.MARGEM, Espaco.XXL)
    lay.setSpacing(Espaco.XL - 4)
    _MargemResponsiva(w, Espaco.XL + 8, Espaco.XXL)
    return lay


def tom_da_situacao(situacao) -> tuple[str, str]:
    from axillares.core.formato import ROTULO_SITUACAO
    from axillares.core.modelos import Situacao

    token = {
        Situacao.SUCESSO: "ok",
        Situacao.FALHA: "falha",
        Situacao.INTERROMPIDA: "aviso",
    }.get(situacao, "tinta_3")
    return ROTULO_SITUACAO.get(situacao, str(situacao)), token


# --- responsividade -----------------------------------------------------------------------------


class GradeResponsiva(QFrame):
    """Grade que escolhe o número de colunas pela largura: 4 → 2 → 1, sem nunca cortar."""

    def __init__(self, min_coluna: int = 220, max_colunas: int = 4, tipo: str = "grade") -> None:
        super().__init__()
        self.setProperty("tipo", tipo)
        self._min = min_coluna
        self._max = max_colunas
        self._itens: list[QWidget] = []
        self._vazias: list[QWidget] = []
        """Células neutras nas posições vazias da última linha: sem elas, o fundo da grade (a cor
        das linhas divisórias) aparecia como um bloco."""
        self._colunas = 0
        self._grade = QGridLayout(self)
        self._grade.setContentsMargins(0, 0, 0, 0)
        self._grade.setSpacing(1)
        # O arranjo atual não pode impor a largura mínima: senão a grade nunca fica estreita o
        # bastante para receber o redimensionamento que a faria usar menos colunas.
        self._grade.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

    def minimumSizeHint(self) -> QSize:
        largura = max((w.minimumSizeHint().width() for w in self._itens), default=0)
        return QSize(largura, super().minimumSizeHint().height())

    def adicionar(self, w: QWidget) -> None:
        self._itens.append(w)
        self._colunas = 0
        self._reorganizar(self.width() or self._min * self._max)

    def _reorganizar(self, largura: int) -> None:
        colunas = max(1, min(self._max, largura // self._min))
        # duas colunas para 4 itens fica melhor que 3 + 1 sozinho
        if colunas == 3 and len(self._itens) == 4:
            colunas = 2
        if colunas == self._colunas:
            return
        self._colunas = colunas
        for w in self._itens:
            self._grade.removeWidget(w)
        for w in self._vazias:
            self._grade.removeWidget(w)
            w.deleteLater()
        self._vazias = []
        for i, w in enumerate(self._itens):
            self._grade.addWidget(w, i // colunas, i % colunas)
        sobra = (-len(self._itens)) % colunas if len(self._itens) > colunas else 0
        for k in range(sobra):
            vazia = QFrame()
            vazia.setProperty("tipo", "celula-vazia")
            i = len(self._itens) + k
            self._grade.addWidget(vazia, i // colunas, i % colunas)
            self._vazias.append(vazia)
        for c in range(self._max):
            self._grade.setColumnStretch(c, 1 if c < colunas else 0)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._reorganizar(self.width())


class LinhaResponsiva(QWidget):
    """Lado a lado quando cabe; um embaixo do outro quando a largura é menor que `limiar`."""

    def __init__(self, limiar: int = 760, espaco: int = Espaco.L) -> None:
        super().__init__()
        self._limiar = limiar
        self.caixa = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.caixa.setContentsMargins(0, 0, 0, 0)
        self.caixa.setSpacing(espaco)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        direcao = (
            QBoxLayout.Direction.LeftToRight
            if self.width() >= self._limiar
            else QBoxLayout.Direction.TopToBottom
        )
        if self.caixa.direction() != direcao:
            self.caixa.setDirection(direcao)


class _MargemResponsiva(QObject):
    """Margens laterais que encolhem em telas estreitas (56 → 32 → 18 px)."""

    def __init__(self, alvo: QWidget, topo: int, base: int) -> None:
        super().__init__(alvo)
        self._topo, self._base = topo, base
        alvo.installEventFilter(self)

    def eventFilter(self, obj, evento) -> bool:
        if evento.type() == QEvent.Type.Resize:
            largura = obj.width()
            lado = Espaco.MARGEM if largura >= 1000 else 32 if largura >= 720 else 18
            lay = obj.layout()
            if lay is not None and lay.contentsMargins().left() != lado:
                lay.setContentsMargins(lado, self._topo, lado, self._base)
        return False


# --- segmentos ----------------------------------------------------------------------------------


def segmentos(opcoes: list[tuple[str, object]], ao_mudar) -> tuple[QHBoxLayout, QButtonGroup]:
    lay = QHBoxLayout()
    lay.setSpacing(0)
    grupo = QButtonGroup(lay)
    for i, (texto, valor) in enumerate(opcoes):
        b = QPushButton(texto)
        b.setProperty("tipo", "segmento")
        b.setProperty("posicao", "inicio" if i == 0 else "fim" if i == len(opcoes) - 1 else "meio")
        b.setFont(t.fonte(Papel.SEGMENTO))
        b.setCheckable(True)
        b.setChecked(i == 0)
        b.setMinimumWidth(48)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False, v=valor: ao_mudar(v))
        grupo.addButton(b, i)
        lay.addWidget(b)
    return lay, grupo
