"""EditorCodigo: o Monaco num QWebEngineView, com uma ponte de sinais para o Python.

O widget não toca no disco: recebe texto, emite pedidos de gravação. Quem lê e grava é a tela,
em segundo plano, pelas funções de core.fontes.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from axillares.core.modelos import Local
from axillares.gui import tema as t

PAGINA = Path(__file__).parent / "pagina.html"


class Ponte(QObject):
    """Objeto exposto ao JavaScript como `ponte`."""

    pronto_sinal = Signal()
    sujo_sinal = Signal(str, bool)
    cursor_sinal = Signal(int, int, str)
    salvar_sinal = Signal(str, str, int)
    acao_sinal = Signal(str)
    mudou_sinal = Signal(str, str)
    pedir_sinal = Signal(int, str, str, str)
    abrir_em_sinal = Signal(str, int, int)

    @Slot()
    def pronto(self) -> None:
        self.pronto_sinal.emit()

    @Slot(str, bool)
    def sujo(self, caminho: str, sujo: bool) -> None:
        self.sujo_sinal.emit(caminho, sujo)

    @Slot(int, int, str)
    def cursor(self, linha: int, coluna: int, linguagem: str) -> None:
        self.cursor_sinal.emit(linha, coluna, linguagem)

    @Slot(str, str, int)
    def salvar(self, caminho: str, texto: str, versao: int) -> None:
        self.salvar_sinal.emit(caminho, texto, versao)

    @Slot(str)
    def acao(self, nome: str) -> None:
        self.acao_sinal.emit(nome)

    @Slot(str, str)
    def mudou(self, caminho: str, texto: str) -> None:
        self.mudou_sinal.emit(caminho, texto)

    @Slot(int, str, str, str)
    def pedir(self, ident: int, tipo: str, caminho: str, dados: str) -> None:
        self.pedir_sinal.emit(ident, tipo, caminho, dados)

    @Slot(str, int, int)
    def abrirEm(self, caminho: str, linha: int, coluna: int) -> None:
        self.abrir_em_sinal.emit(caminho, linha, coluna)


class _Pagina(QWebEnginePage):
    """Só a própria página local carrega; links externos nunca abrem dentro do editor."""

    def acceptNavigationRequest(self, url: QUrl, tipo, principal: bool) -> bool:
        return url.isLocalFile() and url.toLocalFile() == str(PAGINA)


class EditorCodigo(QWidget):
    pronto = Signal()
    sujo_mudou = Signal(Path, bool)
    cursor_mudou = Signal(int, int, str)
    salvar_pedido = Signal(Path, str, int)
    acao_pedida = Signal(str)
    texto_mudou = Signal(Path, str)
    """O usuário editou (após uma pausa na digitação): o texto inteiro, para o servidor."""
    pedido_linguagem = Signal(int, str, Path, dict)
    """(id, tipo, arquivo, dados) — responda com `responder(id, ...)`."""
    abrir_em = Signal(Path, int, int)
    """Ir à definição caiu em outro arquivo: abrir a aba nele."""

    def __init__(self) -> None:
        super().__init__()
        self._pronto = False
        self._fila: list[tuple[str, tuple, object]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.visao = QWebEngineView()
        self.visao.setPage(_Pagina(self.visao))
        self.visao.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.visao.page().setBackgroundColor(QColor(t.paleta().fundo))
        ajustes = self.visao.settings()
        ajustes.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        ajustes.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        ajustes.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        lay.addWidget(self.visao)

        self.ponte = Ponte()
        self.canal = QWebChannel(self)
        self.canal.registerObject("ponte", self.ponte)
        self.visao.page().setWebChannel(self.canal)
        self.ponte.pronto_sinal.connect(self._ficou_pronto)
        self.ponte.sujo_sinal.connect(lambda c, s: self.sujo_mudou.emit(Path(c), s))
        self.ponte.cursor_sinal.connect(self.cursor_mudou)
        self.ponte.salvar_sinal.connect(lambda c, x, v: self.salvar_pedido.emit(Path(c), x, v))
        self.ponte.acao_sinal.connect(self.acao_pedida)
        self.ponte.mudou_sinal.connect(lambda c, x: self.texto_mudou.emit(Path(c), x))
        self.ponte.pedir_sinal.connect(self._pedido)
        self.ponte.abrir_em_sinal.connect(lambda c, lin, col: self.abrir_em.emit(Path(c), lin, col))

        t.tema().mudou.connect(self._tema_mudou)
        self.visao.loadFinished.connect(lambda _ok: self.aplicar_tema())
        self.visao.load(QUrl.fromLocalFile(str(PAGINA)))

    def _pedido(self, ident: int, tipo: str, caminho: str, dados: str) -> None:
        self.pedido_linguagem.emit(ident, tipo, Path(caminho), json.loads(dados or "{}"))

    def _tema_mudou(self, _paleta: object) -> None:
        self.aplicar_tema()

    @property
    def esta_pronto(self) -> bool:
        return self._pronto

    def _ficou_pronto(self) -> None:
        self._pronto = True
        self.aplicar_tema()
        fila, self._fila = self._fila, []
        for funcao, argumentos, retorno in fila:
            self._js(funcao, *argumentos, retorno=retorno)
        self.pronto.emit()

    def _js(self, funcao: str, *argumentos: object, retorno=None) -> None:
        # Antes de a página avisar que está pronta, window.axil pode nem existir: o comando
        # esperaria em vão. Os pedidos ficam na fila e saem todos, em ordem, no "pronto".
        if not self._pronto and funcao != "tema":
            self._fila.append((funcao, argumentos, retorno))
            return
        args = ", ".join(json.dumps(a, ensure_ascii=False) for a in argumentos)
        codigo = f"window.axil && window.axil.{funcao}({args})"
        if retorno is None:
            self.visao.page().runJavaScript(codigo)
        else:
            self.visao.page().runJavaScript(codigo, 0, retorno)

    # --- comandos ---------------------------------------------------------------------------

    def aplicar_tema(self) -> None:
        pal = t.paleta()
        self.visao.page().setBackgroundColor(QColor(pal.fundo))
        self._js("tema", t.tema_editor(pal))

    def abrir(self, caminho: Path, texto: str) -> None:
        self._js("abrir", str(caminho), texto)

    def recarregar(self, caminho: Path, texto: str) -> None:
        self._js("recarregar", str(caminho), texto)

    def fechar(self, caminho: Path) -> None:
        self._js("fechar", str(caminho))

    def marcar_salvo(self, caminho: Path, versao: int) -> None:
        self._js("salvo", str(caminho), versao)

    def salvar(self, caminho: Path | None = None) -> None:
        self._js("pedirSalvar", str(caminho) if caminho else None)

    def salvar_todos(self) -> None:
        self._js("pedirSalvarTodos")

    def problemas(self, caminho: Path, locais: list[Local], dono: str = "fluxo") -> None:
        """dono: "fluxo", "verible" ou "verilator" — cada um tem os próprios marcadores."""
        self._js(
            "problemas",
            str(caminho),
            [
                {"linha": x.linha, "coluna": x.coluna, "mensagem": x.mensagem,
                 "gravidade": x.gravidade, "origem": x.origem}
                for x in locais
            ],
            dono,
        )  # fmt: skip

    def responder(
        self, ident: int, resultado: object, textos: dict[Path, str] | None = None
    ) -> None:
        """Resposta a um `pedido_linguagem`. `textos`: arquivos citados que o editor ainda não
        tem carregados (para espiar a definição, por exemplo)."""
        carregar = {str(c): x for c, x in (textos or {}).items()}
        self._js("resposta", ident, {"resultado": resultado, "textos": carregar})

    def acao(self, nome: str) -> None:
        """Roda uma ação do Monaco pelo id (editor.action.formatDocument, …)."""
        self._js("acao", nome)

    def ir_para(self, caminho: Path, linha: int, coluna: int = 1) -> None:
        self._js("irPara", str(caminho), linha, coluna)

    def sondar(self, retorno) -> None:
        """Para testes: devolve o estado do editor (JSON) ao `retorno`."""
        self._js("_sonda", retorno=lambda s: retorno(json.loads(s) if s else {}))
