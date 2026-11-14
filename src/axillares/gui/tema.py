"""Tema visual do Axillares — linguagem Phareon, em modo escuro e claro.

Único lugar do código com cor, espaçamento e tipografia. As telas pedem papéis
(`Papel.EYEBROW`, `paleta().acento`), nunca valores. A folha QSS mora em `estilo.qss` e usa
`${token}`; quem quiser substituí-la coloca a sua em ~/.config/axillares/estilo.qss.

Princípios herdados da Phareon:
- o laranja #FF4A1C é sinal de estado e ação, nunca decoração, e não muda entre modos;
- mono sempre ≤13px e com espaçamento positivo; títulos grandes com espaçamento negativo;
- serifa itálica só na palavra que toca a física, no máximo uma por título.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from enum import Enum, StrEnum
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

PASTA = Path(__file__).parent
PASTA_FONTES = PASTA / "fontes"
QSS_PADRAO = PASTA / "estilo.qss"
QSS_DO_USUARIO = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / (
    "axillares/estilo.qss"
)


# --- Cor ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Paleta:
    nome: str
    escura: bool
    # terreno
    fundo: str
    fundo_2: str
    fundo_3: str
    # tinta
    tinta: str
    tinta_2: str
    tinta_3: str
    """Só etiqueta redundante: não passa AA. Nunca carrega informação única."""
    # linhas (hairlines)
    linha: str
    linha_media: str
    linha_forte: str
    # sinal — idêntico nos dois modos
    acento: str = "#FF4A1C"
    acento_brilho: str = "#FF6B3D"
    acento_suave: str = "rgba(255, 74, 28, 31)"
    sobre_acento: str = "#0A0A0D"
    # vereditos — extensão do Axillares, só em indicadores de situação
    ok: str = "#4CC38A"
    falha: str = "#F2555A"
    aviso: str = "#E8B34A"

    def qcolor(self, token: str) -> QColor:
        return _qcolor(getattr(self, token))


ESCURO = Paleta(
    nome="escuro",
    escura=True,
    fundo="#08080B",
    fundo_2="#0E0E12",
    fundo_3="#14141A",
    tinta="#F4F1E9",
    tinta_2="#A8A39A",
    tinta_3="#5C594F",
    linha="rgba(244, 241, 233, 20)",
    linha_media="rgba(244, 241, 233, 33)",
    linha_forte="rgba(244, 241, 233, 46)",
)

CLARO = Paleta(
    nome="claro",
    escura=False,
    fundo="#EFECE4",
    fundo_2="#E5E1D7",
    fundo_3="#DBD6CA",
    tinta="#0A0A0D",
    tinta_2="#2A2823",
    tinta_3="#6F6B5F",
    linha="rgba(10, 10, 13, 26)",
    linha_media="rgba(10, 10, 13, 38)",
    linha_forte="rgba(10, 10, 13, 51)",
    ok="#1E7B4F",
    falha="#C42B30",
    aviso="#8F6200",
)


def _qcolor(valor: str) -> QColor:
    if valor.startswith("rgba("):
        r, g, b, a = (int(x) for x in valor[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(valor)


# --- Espaço e forma ---------------------------------------------------------------------------


class Espaco:
    XS = 4
    S = 8
    M = 16
    L = 24
    XL = 40
    XXL = 64
    TRAMA = 80
    """Passo da trama de fundo — a metade "engenharia" da marca."""
    MARGEM = 56
    TRILHO = 232
    """Largura do trilho de navegação."""


class Raio:
    XS = 2
    S = 4
    L = 8
    PILULA = 999


class Movimento:
    """Durações em ms. Curva: OutCubic aproxima o `--ease` da Phareon (desaceleração de
    instrumento, sem bounce)."""

    RESPOSTA = 250
    ESTADO = 400
    PULSO = 3000
    animar = os.environ.get("AXIL_SEM_ANIMACAO", "") == ""


# --- Tipografia -------------------------------------------------------------------------------


class Familia(StrEnum):
    DISPLAY = "Bricolage Grotesque"
    CORPO = "Geist"
    MONO = "Geist Mono"
    SERIFA = "Instrument Serif"


@dataclass(frozen=True)
class Estilo:
    familia: Familia
    tamanho: int
    peso: int = 400
    espacamento_em: float = 0.0
    caixa_alta: bool = False
    italico: bool = False


class Papel(Enum):
    HERO = Estilo(Familia.DISPLAY, 46, 500, -0.035)
    TITULO = Estilo(Familia.DISPLAY, 24, 500, -0.02)
    METRICA = Estilo(Familia.DISPLAY, 40, 400, -0.04)
    MARCA = Estilo(Familia.DISPLAY, 21, 600, -0.03)
    LEAD = Estilo(Familia.CORPO, 16, 400)
    CORPO = Estilo(Familia.CORPO, 14, 400)
    CORPO_FORTE = Estilo(Familia.CORPO, 14, 500)
    PEQUENO = Estilo(Familia.CORPO, 13, 400)
    BOTAO = Estilo(Familia.CORPO, 14, 500, 0.01)
    EYEBROW = Estilo(Familia.MONO, 11, 500, 0.18, caixa_alta=True)
    NUMERO_SECAO = Estilo(Familia.MONO, 11, 500, 0.2, caixa_alta=True)
    ROTULO = Estilo(Familia.MONO, 10, 400, 0.2, caixa_alta=True)
    ETIQUETA = Estilo(Familia.MONO, 10, 500, 0.15, caixa_alta=True)
    MONO = Estilo(Familia.MONO, 12, 400, 0.04)
    NAV = Estilo(Familia.MONO, 11, 500, 0.12, caixa_alta=True)


def fonte(papel: Papel) -> QFont:
    e = papel.value
    f = QFont(e.familia.value)
    f.setPixelSize(e.tamanho)
    f.setWeight(QFont.Weight(e.peso))
    f.setItalic(e.italico)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if e.espacamento_em:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, e.espacamento_em * e.tamanho)
    if e.caixa_alta:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    if e.familia is Familia.CORPO:
        f.setFeature(QFont.Tag("ss01"), 1)
        f.setFeature(QFont.Tag("cv11"), 1)
    return f


def serifa(texto: str, cor: str | None = None, tamanho_px: int | None = None) -> str:
    """Trecho em serifa itálica para rich text — a palavra que toca a física."""
    estilo = f"font-family:'{Familia.SERIFA.value}'; font-style:italic; font-weight:400;"
    if cor:
        estilo += f" color:{cor};"
    if tamanho_px:
        estilo += f" font-size:{tamanho_px}px;"
    return f'<span style="{estilo}">{texto}</span>'


_fontes_carregadas = False


def carregar_fontes() -> list[str]:
    """Registra as fontes embutidas (SIL OFL 1.1). Devolve as famílias registradas."""
    global _fontes_carregadas
    familias: list[str] = []
    if _fontes_carregadas:
        return familias
    for arquivo in sorted(PASTA_FONTES.glob("*.ttf")):
        ident = QFontDatabase.addApplicationFont(str(arquivo))
        if ident >= 0:
            familias += QFontDatabase.applicationFontFamilies(ident)
    _fontes_carregadas = True
    return familias


# --- Modo e aplicação -------------------------------------------------------------------------


class Modo(StrEnum):
    SISTEMA = "sistema"
    ESCURO = "escuro"
    CLARO = "claro"


def _sistema_e_escuro() -> bool:
    dicas = QGuiApplication.styleHints()
    return dicas.colorScheme() != Qt.ColorScheme.Light


def resolver(modo: Modo) -> Paleta:
    if modo is Modo.SISTEMA:
        return ESCURO if _sistema_e_escuro() else CLARO
    return ESCURO if modo is Modo.ESCURO else CLARO


def folha_de_estilo(paleta: Paleta) -> str:
    origem = QSS_DO_USUARIO if QSS_DO_USUARIO.is_file() else QSS_PADRAO
    tokens = {
        **asdict(paleta),
        "raio_s": Raio.S,
        "raio_l": Raio.L,
        "raio_pilula": Raio.PILULA,
        "fam_corpo": Familia.CORPO.value,
        "fam_mono": Familia.MONO.value,
        "fam_display": Familia.DISPLAY.value,
    }
    return Template(origem.read_text(encoding="utf-8")).safe_substitute(tokens)


def _qpalette(p: Paleta) -> QPalette:
    q = QPalette()
    R = QPalette.ColorRole
    pares = {
        R.Window: p.fundo,
        R.Base: p.fundo_2,
        R.AlternateBase: p.fundo_3,
        R.WindowText: p.tinta,
        R.Text: p.tinta,
        R.ButtonText: p.tinta,
        R.Button: p.fundo_2,
        R.PlaceholderText: p.tinta_3,
        R.ToolTipBase: p.fundo_3,
        R.ToolTipText: p.tinta,
        R.Highlight: p.acento,
        R.HighlightedText: p.sobre_acento,
        R.Link: p.acento,
    }
    for papel, cor in pares.items():
        q.setColor(papel, _qcolor(cor))
    return q


class Tema(QObject):
    """Estado do tema da aplicação. Widgets que se desenham sozinhos escutam `mudou`."""

    mudou = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._config = QSettings("Axillares", "axillares")
        bruto = self._config.value("tema/modo", Modo.SISTEMA.value)
        self.modo = Modo(bruto) if bruto in Modo._value2member_map_ else Modo.SISTEMA
        self.paleta = resolver(self.modo)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._sistema_mudou)

    def aplicar(self, modo: Modo | None = None) -> None:
        if modo is not None:
            self.modo = modo
            self._config.setValue("tema/modo", modo.value)
        self.paleta = resolver(self.modo)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setPalette(_qpalette(self.paleta))
            app.setStyleSheet(folha_de_estilo(self.paleta))
        self.mudou.emit(self.paleta)

    def _sistema_mudou(self, *_: object) -> None:
        if self.modo is Modo.SISTEMA:
            self.aplicar()


_tema: Tema | None = None


def tema() -> Tema:
    global _tema
    if _tema is None:
        _tema = Tema()
    return _tema


def paleta() -> Paleta:
    return tema().paleta
