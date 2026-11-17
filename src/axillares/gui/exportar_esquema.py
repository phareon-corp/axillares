"""Exportar o esquemático: imagem, vetor e prancha técnica.

- PNG em 1×, 2× ou 4×, com o fundo do tema ou transparente;
- SVG vetorial (abre no Inkscape, no LibreOffice e em programas de CAD que importam SVG);
- PDF do tamanho do desenho;
- prancha técnica em PDF (A4 a A1): moldura com margem de arquivamento à esquerda, zonas de
  referência nas bordas (1, 2, 3… e A, B, C…), carimbo no canto inferior direito com título,
  projeto, nível, autor, data, revisão, escala e folha, e legenda opcional;
- caderno PDF: várias pranchas num arquivo só (todos os módulos e as células usadas).

Estilo "impressão" desenha preto no branco, sem preenchimentos — o que se espera de uma prancha.
Tudo é desenhado pelo mesmo `desenhar_esquema` da tela: o que se vê é o que se exporta.
"""

from __future__ import annotations

import string
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from axillares import __version__
from axillares.core.esquema import Esquema
from axillares.gui import tema as t
from axillares.gui.tema import Papel
from axillares.gui.visor_esquema import Cores, EstadoSimulacao, desenhar_esquema

FOLHAS = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3,
          "A2": QPageSize.PageSizeId.A2, "A1": QPageSize.PageSizeId.A1}  # fmt: skip
FORMATOS = {".png": "png", ".svg": "svg", ".pdf": "pdf"}
DPI_PDF = 300


@dataclass
class Carimbo:
    titulo: str = ""
    projeto: str = ""
    nivel: str = ""
    descricao: str = ""
    autor: str = ""
    revisao: str = "0"
    data: str = field(default_factory=lambda: date.today().strftime("%d/%m/%Y"))
    pdk: str = ""


@dataclass
class OpcoesExportacao:
    estilo: str = "tema"  # tema · impressao
    escala_png: int = 2
    transparente: bool = False
    prancha: str | None = None  # None (do tamanho do desenho) · A4 · A3 · A2 · A1
    legenda: bool = True
    carimbo: Carimbo = field(default_factory=Carimbo)

    def cores(self) -> Cores:
        return Cores.impressao() if self.estilo == "impressao" else Cores.do_tema()


@dataclass
class Pagina:
    esquema: Esquema
    subtitulo: str = ""
    estado: EstadoSimulacao | None = None
    titulo: str = ""
    """Título desta folha no carimbo (no caderno, o nome do módulo ou da célula)."""


def exportar(esq: Esquema, destino: Path, opcoes: OpcoesExportacao | None = None,
             estado: EstadoSimulacao | None = None) -> None:  # fmt: skip
    """Exporta um desenho; o formato vem da extensão (.png, .svg ou .pdf)."""
    opcoes = opcoes or OpcoesExportacao()
    formato = FORMATOS.get(destino.suffix.lower())
    if formato is None:
        raise ValueError("Use .png, .svg ou .pdf.")
    if formato == "png":
        _png(esq, destino, opcoes, estado)
    elif formato == "svg":
        _svg(esq, destino, opcoes, estado)
    elif opcoes.prancha:
        exportar_caderno([Pagina(esq, opcoes.carimbo.nivel, estado)], destino, opcoes)
    else:
        _pdf_simples(esq, destino, opcoes, estado)


def _fundo(p: QPainter, r: QRectF, opcoes: OpcoesExportacao, cores: Cores) -> None:
    if not opcoes.transparente:
        p.fillRect(r, cores.fundo)


def _png(esq, destino, opcoes, estado) -> None:
    fator = max(1, int(opcoes.escala_png))
    largura, altura = int(esq.largura) + 1, int(esq.altura) + 1
    imagem = QImage(largura * fator, altura * fator, QImage.Format.Format_ARGB32_Premultiplied)
    imagem.setDotsPerMeterX(int(fator * 72 / 0.0254))
    imagem.setDotsPerMeterY(int(fator * 72 / 0.0254))
    imagem.fill(Qt.GlobalColor.transparent)
    cores = opcoes.cores()
    p = QPainter(imagem)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(fator, fator)
    _fundo(p, QRectF(0, 0, largura, altura), opcoes, cores)
    desenhar_esquema(p, esq, 2.0, cores=cores, estado=estado)
    p.end()
    if not imagem.save(str(destino)):
        raise OSError(f"Não consegui gravar {destino}.")


def _svg(esq, destino, opcoes, estado) -> None:
    from PySide6.QtSvg import QSvgGenerator

    largura, altura = int(esq.largura) + 1, int(esq.altura) + 1
    gerador = QSvgGenerator()
    gerador.setFileName(str(destino))
    gerador.setSize(QSize(largura, altura))
    gerador.setViewBox(QRectF(0, 0, largura, altura))
    gerador.setTitle(f"{esq.nome} — {opcoes.carimbo.nivel or esq.nivel.titulo}")
    gerador.setDescription(f"Esquemático gerado pelo Axillares {__version__}")
    cores = opcoes.cores()
    p = QPainter(gerador)
    _fundo(p, QRectF(0, 0, largura, altura), opcoes, cores)
    desenhar_esquema(p, esq, 2.0, cores=cores, estado=estado)
    p.end()


def _pdf_simples(esq, destino, opcoes, estado) -> None:
    escrita = QPdfWriter(str(destino))
    escrita.setCreator(f"Axillares {__version__}")
    escrita.setTitle(esq.nome)
    tamanho = QSizeF(esq.largura + 2, esq.altura + 2)
    escrita.setPageSize(QPageSize(tamanho, QPageSize.Unit.Point, "desenho"))
    escrita.setPageMargins(QMarginsF(0, 0, 0, 0))
    escrita.setResolution(72)
    cores = opcoes.cores()
    p = QPainter(escrita)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _fundo(p, QRectF(0, 0, tamanho.width(), tamanho.height()), opcoes, cores)
    desenhar_esquema(p, esq, 2.0, cores=cores, estado=estado)
    p.end()


# --- prancha técnica --------------------------------------------------------------------------


def exportar_caderno(paginas: list[Pagina], destino: Path, opcoes: OpcoesExportacao) -> None:
    """Uma prancha por página, numeradas (folha n/N)."""
    if not paginas:
        raise ValueError("Nada para exportar.")
    folha = opcoes.prancha or "A3"
    escrita = QPdfWriter(str(destino))
    escrita.setCreator(f"Axillares {__version__}")
    escrita.setTitle(opcoes.carimbo.titulo or paginas[0].esquema.nome)
    escrita.setResolution(DPI_PDF)
    p: QPainter | None = None
    for i, pagina in enumerate(paginas):
        paisagem = pagina.esquema.largura >= pagina.esquema.altura * 0.75
        layout = QPageLayout(
            QPageSize(FOLHAS.get(folha, QPageSize.PageSizeId.A3)),
            QPageLayout.Orientation.Landscape if paisagem else QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
        if p is None:
            escrita.setPageLayout(layout)
            p = QPainter(escrita)
        else:
            escrita.setPageLayout(layout)
            escrita.newPage()
        desenhar_prancha(p, escrita.width(), escrita.height(), pagina, opcoes, i + 1,
                         len(paginas), folha)  # fmt: skip
    assert p is not None
    p.end()


def _mm(valor: float) -> float:
    return valor * DPI_PDF / 25.4


def desenhar_prancha(
    p: QPainter,
    largura_px: float,
    altura_px: float,
    pagina: Pagina,
    opcoes: OpcoesExportacao,
    numero: int = 1,
    total: int = 1,
    folha: str = "A3",
) -> None:
    """Moldura, zonas, carimbo, legenda e o desenho ajustado à área útil."""
    cores = opcoes.cores()
    tinta = cores.tinta
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRectF(0, 0, largura_px, altura_px), cores.fundo)
    esquerda, margem = _mm(20), _mm(10)
    moldura = QRectF(esquerda, margem, largura_px - esquerda - margem, altura_px - 2 * margem)
    p.setPen(QPen(tinta, _mm(0.7)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(moldura)
    p.setPen(QPen(tinta, _mm(0.25)))
    p.drawRect(QRectF(_mm(5), _mm(5), largura_px - _mm(10), altura_px - _mm(10)))
    _zonas(p, moldura, tinta)

    carimbo = _carimbo(p, moldura, pagina, opcoes, numero, total, folha, tinta)
    area = moldura.adjusted(_mm(6), _mm(6), -_mm(6), -_mm(6))
    area.setBottom(carimbo.top() - _mm(4))
    if opcoes.legenda:
        faixa = QRectF(moldura.left(), carimbo.top(), carimbo.left() - moldura.left(),
                       carimbo.height())  # fmt: skip
        _legenda(p, faixa, pagina, tinta, cores)
    esq = pagina.esquema
    if esq.largura > 0 and esq.altura > 0:
        # ajusta à folha, mas sem ampliar mais que 1,5× o tamanho natural (1 pt = 1/72")
        natural = DPI_PDF / 72.0
        escala = min(area.width() / esq.largura, area.height() / esq.altura, natural * 1.5)
        p.save()
        p.translate(area.left() + (area.width() - esq.largura * escala) / 2,
                    area.top() + (area.height() - esq.altura * escala) / 2)  # fmt: skip
        p.scale(escala, escala)
        desenhar_esquema(p, esq, 2.0, cores=cores, estado=pagina.estado)
        p.restore()
    p.restore()


def _fonte(tamanho_mm: float, negrito: bool = False) -> QFont:
    f = QFont(t.fonte(Papel.MONO))
    f.setPixelSize(max(1, int(_mm(tamanho_mm))))
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
    f.setCapitalization(QFont.Capitalization.MixedCase)
    f.setBold(negrito)
    return f


def _zonas(p: QPainter, moldura: QRectF, tinta: QColor) -> None:
    """Referências nas bordas: colunas numeradas e linhas com letras, a cada ~50 mm."""
    colunas = max(2, round(moldura.width() / _mm(50)))
    linhas = max(2, round(moldura.height() / _mm(50)))
    p.setFont(_fonte(2.5))
    p.setPen(QPen(tinta, _mm(0.25)))
    for i in range(colunas):
        x0 = moldura.left() + moldura.width() * i / colunas
        x1 = moldura.left() + moldura.width() * (i + 1) / colunas
        if i:
            p.drawLine(QPointF(x0, moldura.top() - _mm(5)), QPointF(x0, moldura.top()))
            p.drawLine(QPointF(x0, moldura.bottom()), QPointF(x0, moldura.bottom() + _mm(5)))
        for y in (moldura.top() - _mm(5), moldura.bottom()):
            p.drawText(QRectF(x0, y, x1 - x0, _mm(5)), Qt.AlignmentFlag.AlignCenter, str(i + 1))
    for j in range(linhas):
        y0 = moldura.top() + moldura.height() * j / linhas
        y1 = moldura.top() + moldura.height() * (j + 1) / linhas
        letra = string.ascii_uppercase[j % 26]
        if j:
            p.drawLine(QPointF(moldura.right(), y0), QPointF(moldura.right() + _mm(5), y0))
            p.drawLine(QPointF(moldura.left() - _mm(5), y0), QPointF(moldura.left(), y0))
        p.drawText(QRectF(moldura.right(), y0, _mm(5), y1 - y0), Qt.AlignmentFlag.AlignCenter,
                   letra)  # fmt: skip
        p.drawText(QRectF(moldura.left() - _mm(5), y0, _mm(5), y1 - y0),
                   Qt.AlignmentFlag.AlignCenter, letra)  # fmt: skip


def _celula(p: QPainter, r: QRectF, rotulo: str, valor: str, tinta: QColor,
            tamanho: float = 3.2, negrito: bool = False) -> None:  # fmt: skip
    p.setPen(QPen(tinta, _mm(0.35)))
    p.drawRect(r)
    p.setFont(_fonte(1.8))
    p.drawText(r.adjusted(_mm(1.2), _mm(0.8), 0, 0),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, rotulo.upper())  # fmt: skip
    f = _fonte(tamanho, negrito)
    p.setFont(f)
    texto = QFontMetricsF(f).elidedText(valor, Qt.TextElideMode.ElideRight, r.width() - _mm(2.4))
    p.drawText(r.adjusted(_mm(1.2), 0, -_mm(1.2), -_mm(1)),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, texto)  # fmt: skip


def _carimbo(p, moldura, pagina, opcoes, numero, total, folha, tinta) -> QRectF:
    c = opcoes.carimbo
    largura = min(_mm(180), moldura.width())
    altura = _mm(36)
    r = QRectF(moldura.right() - largura, moldura.bottom() - altura, largura, altura)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(tinta, _mm(0.7)))
    p.drawRect(r)
    h = altura / 3
    marca = QRectF(r.left(), r.top(), largura * 0.24, h * 2)
    p.setPen(QPen(tinta, _mm(0.35)))
    p.drawRect(marca)
    p.setFont(_fonte(4.2, negrito=True))
    p.drawText(marca.adjusted(0, -_mm(3), 0, 0), Qt.AlignmentFlag.AlignCenter, "AXILLARES")
    p.setFont(_fonte(1.8))
    p.drawText(marca.adjusted(0, _mm(6), 0, 0), Qt.AlignmentFlag.AlignCenter,
               f"do Verilog ao GDSII · v{__version__}")  # fmt: skip
    resto = r.left() + marca.width()
    larg_resto = largura - marca.width()
    titulo = pagina.titulo or c.titulo or pagina.esquema.nome
    _celula(p, QRectF(resto, r.top(), larg_resto, h), "título", titulo, tinta, 4.0, True)
    nivel = pagina.subtitulo or c.nivel or pagina.esquema.nivel.titulo
    _celula(p, QRectF(resto, r.top() + h, larg_resto * 0.5, h), "projeto", c.projeto, tinta)
    _celula(p, QRectF(resto + larg_resto * 0.5, r.top() + h, larg_resto * 0.5, h), "desenho",
            nivel, tinta)  # fmt: skip
    campos = [("autor", c.autor or "—"), ("data", c.data), ("revisão", c.revisao),
              ("escala", "S/E"), ("folha", f"{numero}/{total} · {folha}"),
              ("pdk", c.pdk or "—")]  # fmt: skip
    pesos = [0.28, 0.17, 0.1, 0.1, 0.18, 0.17]
    x = r.left()
    for (rotulo, valor), peso in zip(campos, pesos, strict=True):
        w = largura * peso
        _celula(p, QRectF(x, r.top() + 2 * h, w, h), rotulo, valor, tinta, 2.8)
        x += w
    return r


def _legenda(p, r: QRectF, pagina: Pagina, tinta: QColor, cores: Cores) -> QRectF:
    """Componentes do desenho e, com simulação, o código de cores dos fios."""
    esq = pagina.esquema
    contagem = Counter((b.rotulo or b.tipo.lstrip("$")) for b in esq.componentes())
    if not contagem:
        return r
    caixa = QRectF(r.left() + _mm(4), r.top() + _mm(2), min(r.width() - _mm(8), _mm(150)),
                   r.height() - _mm(4))  # fmt: skip
    if caixa.width() < _mm(40):
        return r
    p.setPen(QPen(tinta, _mm(0.25)))
    p.drawRect(caixa)
    p.setFont(_fonte(1.8))
    p.drawText(caixa.adjusted(_mm(1.5), _mm(1), 0, 0),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "LEGENDA")  # fmt: skip
    p.setFont(_fonte(2.4))
    itens = [f"{n}× {nome}" for nome, n in contagem.most_common()]
    colunas = 3
    por_coluna = max(1, -(-len(itens) // colunas))
    altura_linha = _mm(3.4)
    for i, texto in enumerate(itens[: por_coluna * colunas]):
        col, lin = divmod(i, por_coluna)
        x = caixa.left() + _mm(2) + col * (caixa.width() - _mm(4)) / colunas
        y = caixa.top() + _mm(4.5) + lin * altura_linha
        if y + altura_linha > caixa.bottom() - (_mm(5) if pagina.estado else 0):
            continue
        p.drawText(QPointF(x, y + altura_linha * 0.8), texto)
    if pagina.estado is not None:
        y = caixa.bottom() - _mm(3)
        x = caixa.left() + _mm(2)
        for nome, cor in (("1", cores.nivel1), ("0", cores.nivel0), ("X", cores.indefinido),
                          ("Z", cores.solto), ("barramento", cores.barramento)):  # fmt: skip
            p.setPen(QPen(cor, _mm(0.8)))
            p.drawLine(QPointF(x, y - _mm(0.8)), QPointF(x + _mm(5), y - _mm(0.8)))
            p.setPen(tinta)
            p.drawText(QPointF(x + _mm(6), y), nome)
            x += _mm(6) + QFontMetricsF(p.font()).horizontalAdvance(nome) + _mm(4)
        t_ns = pagina.estado.t_ns
        p.drawText(QPointF(x + _mm(2), y), f"instante t = {t_ns:g} ns")
    return caixa
