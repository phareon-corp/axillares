"""O fluxo explicado: um cartão por passo, que acende ao vivo durante a execução."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from axillares.core import explicacoes as ex
from axillares.core.modelos import Etapa
from axillares.gui.componentes import GradeResponsiva, repolir, rotulo
from axillares.gui.tema import Espaco, Papel

COLUNAS = 3


class CartaoPasso(QFrame):
    def __init__(self, numero: int, passo: ex.Passo, so_gds: bool) -> None:
        super().__init__()
        self.passo = passo
        self.setProperty("tipo", "cartao-passo")
        self.setProperty("estado", "parado")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.M + 2, Espaco.M, Espaco.M + 2, Espaco.M)
        lay.setSpacing(6)
        topo = QHBoxLayout()
        topo.setSpacing(Espaco.S)
        self.numero = rotulo(f"{numero:02d}", Papel.NUMERO_SECAO, "acento")
        topo.addWidget(self.numero)
        topo.addWidget(rotulo(passo.ferramenta, Papel.ROTULO, "3"))
        topo.addStretch(1)
        self.marca = rotulo("só no GDS" if so_gds else "", Papel.ROTULO, "3")
        topo.addWidget(self.marca)
        lay.addLayout(topo)
        lay.addWidget(rotulo(passo.titulo, Papel.CORPO_FORTE))
        o_que = rotulo(passo.o_que, Papel.PEQUENO, "2")
        o_que.setWordWrap(True)
        lay.addWidget(o_que)
        self.detalhe = QWidget()
        dl = QVBoxLayout(self.detalhe)
        dl.setContentsMargins(0, Espaco.S, 0, 0)
        dl.setSpacing(6)
        for nome, texto in (
            ("entra", passo.entra),
            ("sai", passo.sai),
            ("observe", passo.observar),
        ):
            dl.addWidget(rotulo(nome, Papel.ROTULO, "3"))
            r = rotulo(texto, Papel.PEQUENO)
            r.setWordWrap(True)
            dl.addWidget(r)
        self.detalhe.hide()
        lay.addWidget(self.detalhe)
        lay.addStretch(1)
        self._so_gds = so_gds

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.detalhe.setVisible(not self.detalhe.isVisible())

    def definir(self, estado: str) -> None:
        """parado · agora · feito · falhou"""
        self.setProperty("estado", estado)
        textos = {"agora": "agora", "feito": "✓ feito", "falhou": "✕ falhou"}
        self.marca.setText(textos.get(estado, "só no GDS" if self._so_gds else ""))
        self.marca.setProperty(
            "tom", {"agora": "acento", "feito": "ok", "falhou": "falha"}.get(estado, "3")
        )
        repolir(self)
        repolir(self.marca)


class FluxoExplicado(GradeResponsiva):
    """Grade com os passos do fluxo GDS; os da síntese vêm primeiro e valem para as duas."""

    def __init__(self) -> None:
        super().__init__(min_coluna=260, max_colunas=COLUNAS)
        da_sintese = {p.id for p in ex.etapa(Etapa.SINTESE).passos}
        self.cartoes: dict[str, CartaoPasso] = {}
        for i, passo in enumerate(ex.etapa(Etapa.GDS).passos):
            c = CartaoPasso(i + 1, passo, passo.id not in da_sintese)
            self.adicionar(c)
            self.cartoes[passo.id] = c
        self._ordem = list(self.cartoes)
        self._atual: str | None = None

    def comecar(self, etapa: Etapa) -> None:
        validos = {p.id for p in ex.etapa(etapa).passos}
        for i, c in self.cartoes.items():
            c.definir("parado")
            c.setEnabled(i in validos)
            # pseudo-estado em ancestral não funciona em QSS: a opacidade apaga quem não roda
            efeito = None
            if i not in validos:
                efeito = QGraphicsOpacityEffect(c)
                efeito.setOpacity(0.35)
            c.setGraphicsEffect(efeito)
        self._atual = None

    def avancar(self, no: str) -> ex.Passo | None:
        passo = ex.passo_do_no(no)
        if passo is None or passo.id not in self.cartoes:
            return passo
        if self._atual and self._atual != passo.id:
            self.cartoes[self._atual].definir("feito")
        self._atual = passo.id
        self.cartoes[passo.id].definir("agora")
        return passo

    def terminar(self, sucesso: bool) -> None:
        for i, c in self.cartoes.items():
            if not c.isEnabled():
                c.setEnabled(True)
                c.setGraphicsEffect(None)
                continue
            if i == self._atual:
                c.definir("feito" if sucesso else "falhou")
            elif c.property("estado") == "parado" and sucesso:
                c.definir("feito")
