"""Tela — Layout: o GDS de uma execução desenhado dentro do app.

O desenho é do KLayout da imagem (motor/layout.py), em outro processo. Aqui só se mostra a imagem
e se converte mouse em região: zoom no cursor, arrasto, enquadrar. Enquanto a nova região é
desenhada, a imagem anterior é reposicionada na hora — o zoom nunca trava.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares.core import explicacoes as ex
from axillares.core import formato as fmt
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, Situacao, TipoArtefato
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import Eyebrow, botao, rotulo
from axillares.gui.sessao import Sessao
from axillares.gui.telas.execucoes import _segmentos
from axillares.gui.tema import Espaco, Papel

Caixa = tuple[float, float, float, float]
PASSO_ZOOM = 1.25


class Prancheta(QWidget):
    """Área de desenho: estado de vista (centro e µm por pixel) e a imagem mais recente."""

    vista_mudou = Signal()
    cursor_um = Signal(float, float)
    clique_um = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.centro = QPointF(0, 0)
        self.escala = 0.05  # µm por pixel lógico
        self.limites: Caixa | None = None
        self._imagem: QPixmap | None = None
        self._caixa_imagem: Caixa | None = None
        self._arrasto: QPointF | None = None
        self._inicio_clique: QPointF | None = None
        self.destaque: Caixa | None = None
        t.tema().mudou.connect(lambda _p: self.update())

    # --- geometria ----------------------------------------------------------------------------

    def caixa(self) -> Caixa:
        w, h = self.width() * self.escala, self.height() * self.escala
        return (self.centro.x() - w / 2, self.centro.y() - h / 2,
                self.centro.x() + w / 2, self.centro.y() + h / 2)  # fmt: skip

    def para_um(self, p: QPointF) -> QPointF:
        x1, _y1, _x2, y2 = self.caixa()
        return QPointF(x1 + p.x() * self.escala, y2 - p.y() * self.escala)

    def enquadrar(self) -> None:
        if not self.limites or self.width() < 2:
            return
        x1, y1, x2, y2 = self.limites
        margem = 1.08
        self.escala = max((x2 - x1) / self.width(), (y2 - y1) / self.height()) * margem
        self.centro = QPointF((x1 + x2) / 2, (y1 + y2) / 2)
        self.update()
        self.vista_mudou.emit()

    def definir_imagem(self, imagem: QImage, caixa: Caixa) -> None:
        self._imagem = QPixmap.fromImage(imagem)
        self._imagem.setDevicePixelRatio(1.0)
        self._caixa_imagem = caixa
        self.update()

    def limpar(self) -> None:
        self._imagem = None
        self._caixa_imagem = None
        self.update()

    # --- desenho ------------------------------------------------------------------------------

    def paintEvent(self, _e: QPaintEvent) -> None:
        pal = t.paleta()
        p = QPainter(self)
        p.fillRect(self.rect(), pal.qcolor("fundo"))
        if self._imagem is not None and self._caixa_imagem is not None:
            x1, _y1, _x2, y2 = self.caixa()
            ix1, iy1, ix2, iy2 = self._caixa_imagem
            alvo = QRectF(
                (ix1 - x1) / self.escala,
                (y2 - iy2) / self.escala,
                (ix2 - ix1) / self.escala,
                (iy2 - iy1) / self.escala,
            )
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(alvo, self._imagem, QRectF(self._imagem.rect()))
        if self.destaque is not None:
            x1, _y1, _x2, y2 = self.caixa()
            dx1, dy1, dx2, dy2 = self.destaque
            r = QRectF((dx1 - x1) / self.escala, (y2 - dy2) / self.escala,
                       (dx2 - dx1) / self.escala, (dy2 - dy1) / self.escala)  # fmt: skip
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            halo = pal.qcolor("acento")
            halo.setAlphaF(0.18)
            p.fillRect(r, halo)
            p.setPen(QPen(pal.qcolor("acento"), 2))
            p.drawRect(r)
        self._regua(p)

    def _regua(self, p: QPainter) -> None:
        """Barra de escala no canto: o número tem unidade (Phareon)."""
        pal = t.paleta()
        alvo_px = 120
        bruto = alvo_px * self.escala
        if bruto <= 0:
            return
        ordem = 10 ** int(f"{bruto:e}".split("e")[1])
        passo = next(m * ordem for m in (1, 2, 5, 10) if m * ordem >= bruto * 0.6)
        comprimento = passo / self.escala
        x0, y0 = 20, self.height() - 22
        placa = pal.qcolor("fundo")
        placa.setAlphaF(0.78)
        p.fillRect(QRectF(x0 - 10, y0 - 26, comprimento + 20, 36), placa)
        p.setPen(QPen(pal.qcolor("tinta"), 2))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + comprimento, y0))
        p.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        p.drawLine(QPointF(x0 + comprimento, y0 - 4), QPointF(x0 + comprimento, y0 + 4))
        p.setFont(t.fonte(Papel.MONO))
        texto = f"{fmt.numero(passo, 0 if passo >= 1 else 3)} µm"
        p.drawText(QPointF(x0, y0 - 9), texto)

    # --- mouse --------------------------------------------------------------------------------

    def wheelEvent(self, evento) -> None:
        passos = evento.angleDelta().y() / 120
        if not passos:
            return
        fator = PASSO_ZOOM**passos
        cursor = evento.position()
        ancora = self.para_um(cursor)
        self.escala = max(1e-5, min(self.escala / fator, 50.0))
        self.centro = QPointF(
            ancora.x() - (cursor.x() - self.width() / 2) * self.escala,
            ancora.y() + (cursor.y() - self.height() / 2) * self.escala,
        )
        self.update()
        self.vista_mudou.emit()

    def mousePressEvent(self, evento: QMouseEvent) -> None:
        if evento.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._arrasto = evento.position()
            self._inicio_clique = evento.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, evento: QMouseEvent) -> None:
        if self._arrasto is not None:
            delta = evento.position() - self._arrasto
            self._arrasto = evento.position()
            self.centro = QPointF(
                self.centro.x() - delta.x() * self.escala,
                self.centro.y() + delta.y() * self.escala,
            )
            self.update()
            self.vista_mudou.emit()
        um = self.para_um(evento.position())
        self.cursor_um.emit(um.x(), um.y())

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:
        inicio, self._inicio_clique = self._inicio_clique, None
        self._arrasto = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        if (
            inicio is not None
            and evento.button() == Qt.MouseButton.LeftButton
            and (evento.position() - inicio).manhattanLength() < 4
        ):
            um = self.para_um(evento.position())
            self.clique_um.emit(um.x(), um.y())

    def mouseDoubleClickEvent(self, _evento: QMouseEvent) -> None:
        self.enquadrar()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        if self._imagem is None and self.limites:
            self.enquadrar()
        else:
            self.vista_mudou.emit()


COMO_FOI_FEITO = (
    (
        "1 · Floorplan",
        "Definiu o contorno do chip, as linhas onde as células moram e a malha de "
        "alimentação: as faixas largas de metal 4 e 5 e os trilhos de metal 1 em cada linha.",
        "Alimentação",
    ),
    (
        "2 · Posicionamento",
        "Pôs cada célula padrão numa linha. Cada retângulo pequeno é uma célula "
        "inteira, desenhada pelo fabricante do PDK — flip-flops, portas, preenchimento.",
        "Células",
    ),
    (
        "3 · Árvore de relógio",
        "Inseriu buffers de relógio (clkbuf) e preencheu os vãos com células "
        "fill e decap. Clique numa célula para ver o que ela é.",
        None,
    ),
    (
        "4 · Roteamento",
        "Desenhou os fios de sinal em metal 1 a 3 e as vias entre eles, ligando os "
        "pinos das células como a netlist manda.",
        "Fios de sinal",
    ),
    (
        "5 · Escrita do GDS",
        "Juntou tudo num arquivo só, camada por camada — o que você vê aqui.",
        None,
    ),
)


class LinhaCamada(QWidget):
    """Uma camada: a amostra é a própria cor do PDK — cheia quando visível, vazada quando oculta.
    (Caixas de seleção laranja aqui estourariam o orçamento de sinal da Phareon.)"""

    alternada = Signal(int, bool)
    isolada = Signal(int)

    def __init__(self, indice: int, nome: str, cor: str, dica: str) -> None:
        super().__init__()
        self.indice = indice
        self.cor = QColor(cor)
        self.visivel = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(dica)
        self.setFixedHeight(24)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 0, 4, 0)
        self.nome = rotulo(nome, Papel.PEQUENO)
        self.nome_camada = nome
        lay.addWidget(self.nome)

    def definir(self, visivel: bool) -> None:
        self.visivel = visivel
        self.nome.setProperty("tom", None if visivel else "3")
        self.nome.style().unpolish(self.nome)
        self.nome.style().polish(self.nome)
        self.update()

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.definir(not self.visivel)
            self.alternada.emit(self.indice, self.visivel)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        quadrado = QRectF(2.5, self.height() / 2 - 6.5, 13, 13)
        p.setPen(QPen(self.cor, 1.5))
        if self.visivel:
            p.setBrush(self.cor)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(quadrado, 2.5, 2.5)


class TelaLayout(QWidget):
    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self.render = None
        self.registro: RegistroExecucao | None = None
        self._ocultas: set[int] = set()
        self._caixas: dict[int, LinhaCamada] = {}
        self._renderizando = False
        self._pendente = False
        self._pedido_inicial: str | None = None
        self._tarefas: list[tarefas.Tarefa] = []

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        centro = QVBoxLayout()
        centro.setSpacing(0)
        topo = QFrame()
        topo.setProperty("tipo", "barra-abas")
        tl = QHBoxLayout(topo)
        tl.setContentsMargins(Espaco.L, Espaco.S + 2, Espaco.M, Espaco.S + 2)
        tl.setSpacing(Espaco.M)
        self.eyebrow = Eyebrow("Layout")
        tl.addWidget(self.eyebrow)
        self.combo = QComboBox()
        self.combo.setFont(t.fonte(Papel.MONO))
        self.combo.setMinimumWidth(300)
        self.combo.currentIndexChanged.connect(self._escolheu)
        tl.addWidget(self.combo)
        tl.addStretch(1)
        self.botao_enquadrar = botao("Enquadrar", "compacto")
        self.botao_enquadrar.clicked.connect(lambda: self.prancheta.enquadrar())
        self.botao_exportar = botao("Exportar PNG…", "compacto")
        self.botao_exportar.clicked.connect(self._exportar)
        tl.addWidget(self.botao_enquadrar)
        tl.addWidget(self.botao_exportar)
        centro.addWidget(topo)

        self.prancheta = Prancheta()
        self.prancheta.vista_mudou.connect(self._agendar)
        self.prancheta.cursor_um.connect(self._mostrar_cursor)
        self.prancheta.clique_um.connect(self._inspecionar)
        centro.addWidget(self.prancheta, 1)

        estado = QFrame()
        estado.setProperty("tipo", "barra-estado")
        el = QHBoxLayout(estado)
        el.setContentsMargins(Espaco.L, 0, Espaco.M, 0)
        el.setSpacing(Espaco.L)
        self.aviso = rotulo("Escolha uma execução com GDS.", Papel.ETIQUETA, "2")
        self.coordenadas = rotulo("", Papel.MONO, "2")
        self.dimensoes = rotulo("", Papel.MONO, "3")
        el.addWidget(self.aviso)
        el.addStretch(1)
        el.addWidget(self.dimensoes)
        el.addWidget(self.coordenadas)
        estado.setFixedHeight(30)
        centro.addWidget(estado)
        raiz.addLayout(centro, 1)

        lateral = QFrame()
        lateral.setProperty("tipo", "lateral-editor")
        lateral.setFixedWidth(310)
        ll = QVBoxLayout(lateral)
        ll.setContentsMargins(Espaco.M + 2, Espaco.L, Espaco.M, Espaco.M)
        ll.setSpacing(Espaco.S)
        self.nome_celula = rotulo("", Papel.TITULO)
        ll.addWidget(rotulo("Célula de topo", Papel.ROTULO, "3"))
        ll.addWidget(self.nome_celula)
        abas, self._grupo_abas = _segmentos(
            [("Camadas", 0), ("Inspetor", 1), ("Como foi feito", 2)], self._trocar_aba
        )
        ll.addLayout(abas)
        self.paginas = QStackedWidget()
        ll.addWidget(self.paginas, 1)

        # 0 — camadas
        pagina = QWidget()
        pl = QVBoxLayout(pagina)
        pl.setContentsMargins(0, Espaco.S, 0, 0)
        pl.setSpacing(Espaco.S)
        filtros, self._grupo_filtros = _segmentos(
            [("Tudo", None), ("Células", "Células"), ("Fios", "Fios de sinal"),
             ("Alimentação", "Alimentação")], self._filtrar,
        )  # fmt: skip
        pl.addLayout(filtros)
        dica = rotulo("clique: liga/desliga · duplo clique: só esta", Papel.ROTULO, "3")
        dica.setWordWrap(True)
        pl.addWidget(dica)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lista = QWidget()
        self._lay_camadas = QVBoxLayout(self._lista)
        self._lay_camadas.setContentsMargins(0, 0, 0, 0)
        self._lay_camadas.setSpacing(2)
        self._lay_camadas.addStretch(1)
        rolagem.setWidget(self._lista)
        pl.addWidget(rolagem, 1)
        self.sobre_camada = rotulo("", Papel.PEQUENO, "2")
        self.sobre_camada.setWordWrap(True)
        pl.addWidget(self.sobre_camada)
        self.paginas.addWidget(pagina)

        # 1 — inspetor
        pagina = QWidget()
        il = QVBoxLayout(pagina)
        il.setContentsMargins(0, Espaco.S, 0, 0)
        il.setSpacing(Espaco.S)
        rol = QScrollArea()
        rol.setWidgetResizable(True)
        rol.setFrameShape(QFrame.Shape.NoFrame)
        rol.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        corpo = QWidget()
        self._lay_inspetor = QVBoxLayout(corpo)
        self._lay_inspetor.setContentsMargins(0, 0, 0, 0)
        self._lay_inspetor.setSpacing(6)
        self._lay_inspetor.addWidget(
            rotulo(
                "Clique em qualquer ponto do desenho para ver o que existe ali.", Papel.PEQUENO, "2"
            )
        )
        self._lay_inspetor.addStretch(1)
        rol.setWidget(corpo)
        il.addWidget(rol, 1)
        self.paginas.addWidget(pagina)

        # 2 — como foi feito
        pagina = QWidget()
        cl = QVBoxLayout(pagina)
        cl.setContentsMargins(0, Espaco.S, 0, 0)
        cl.setSpacing(Espaco.M - 2)
        intro = rotulo(
            "Este desenho não foi feito à mão: o fluxo o montou em camadas, passo a passo.",
            Papel.PEQUENO, "2",
        )  # fmt: skip
        intro.setWordWrap(True)
        cl.addWidget(intro)
        for titulo, texto, grupo in COMO_FOI_FEITO:
            bloco = QVBoxLayout()
            bloco.setSpacing(3)
            bloco.addWidget(rotulo(titulo, Papel.CORPO_FORTE))
            r = rotulo(texto, Papel.PEQUENO, "2")
            r.setWordWrap(True)
            bloco.addWidget(r)
            if grupo:
                ver = botao(f"Ver só: {grupo.lower()} →", "link")
                ver.setFont(t.fonte(Papel.ETIQUETA))
                ver.clicked.connect(lambda _c=False, g=grupo: self._filtrar(g, trocar=True))
                bloco.addWidget(ver, 0, Qt.AlignmentFlag.AlignLeft)
            cl.addLayout(bloco)
        cl.addStretch(1)
        self.paginas.addWidget(pagina)
        raiz.addWidget(lateral)

        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(40)
        self._temporizador.timeout.connect(self._renderizar)
        sessao.execucoes_mudaram.connect(self.recarregar)
        sessao.projeto_mudou.connect(lambda _p: (self._fechar_render(), self.recarregar()))
        t.tema().mudou.connect(lambda _p: self._agendar())

    # --- execuções com GDS --------------------------------------------------------------------

    def _rodar(self, funcao, ao_concluir, ao_falhar=None) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(ao_falhar or self._falhou)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    def recarregar(self) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            return

        def listar() -> list[RegistroExecucao]:
            com_gds = []
            for r in caderno.listar(Etapa.GDS):
                if r.situacao is Situacao.SUCESSO:
                    completo = caderno.carregar(r.id)
                    if any(a.tipo is TipoArtefato.GDS for a in completo.artefatos):
                        com_gds.append(completo)
            return com_gds

        self._rodar(listar, self._preencher)

    def _preencher(self, registros: list[RegistroExecucao]) -> None:
        atual = self.registro.id if self.registro else None
        alvo = self._pedido_inicial or atual
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in registros:
            m = r.metrica("area_total_um2")
            area = f"  {fmt.numero(m.valor, 1)} µm²" if m else ""
            self.combo.addItem(f"#{r.numero}  gds  {fmt.momento(r.inicio)}{area}", r)
        self.combo.blockSignals(False)
        if not registros:
            self.aviso.setText("Nenhuma execução com GDS ainda. Execute a etapa GDS no Projeto.")
            self._fechar_render()
            return
        indice = next((i for i, r in enumerate(registros) if r.id == alvo), 0)
        self._pedido_inicial = None
        if self.combo.currentIndex() != indice:
            self.combo.setCurrentIndex(indice)
        else:
            self._escolheu(indice)

    def mostrar_execucao(self, ident: str) -> None:
        self._pedido_inicial = ident
        self.recarregar()

    def _escolheu(self, indice: int) -> None:
        r = self.combo.itemData(indice)
        if r is None or (self.registro and r.id == self.registro.id and self.render):
            return
        self._fechar_render()
        self.registro = r
        gds = next(a for a in r.artefatos if a.tipo is TipoArtefato.GDS)
        from axillares.motor.layout import RenderizadorLayout

        projeto = self.sessao.projeto
        pdk = r.pdk or (projeto.asic.pdk.value if projeto else "skywater130")
        self.render = RenderizadorLayout(r.diretorio / gds.caminho, pdk)
        self.eyebrow.texto.setText(f"LAYOUT · #{r.numero} · {pdk}".upper())
        self.aviso.setText("Abrindo o GDS no KLayout da imagem…")
        render = self.render
        self._rodar(render.iniciar, lambda info: self._aberto(render, info))

    def _aberto(self, render, info) -> None:
        if render is not self.render:
            return
        self.nome_celula.setText(info.celula)
        x1, y1, x2, y2 = info.caixa
        self.dimensoes.setText(f"{fmt.numero(x2 - x1, 2)} × {fmt.numero(y2 - y1, 2)} µm")
        self._ocultas = set()
        while self._lay_camadas.count() > 1:
            item = self._lay_camadas.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._caixas = {}
        for c in info.camadas:
            linha = LinhaCamada(c.indice, c.nome_curto, c.cor, f"{c.nome} — GDS {c.fonte}")
            linha.alternada.connect(self._alternar)
            linha.isolada.connect(self._isolar)
            self._caixas[c.indice] = linha
            self._lay_camadas.insertWidget(self._lay_camadas.count() - 1, linha)
        self._grupo_filtros.button(0).setChecked(True)
        self.prancheta.destaque = None
        self.prancheta.limites = info.caixa
        self.prancheta.limpar()
        self.prancheta.enquadrar()
        self.aviso.setText("RODA: ZOOM · ARRASTAR: MOVER · DUPLO CLIQUE: ENQUADRAR")

    # --- camadas ------------------------------------------------------------------------------

    def _alternar(self, indice: int, visivel: bool) -> None:
        if visivel:
            self._ocultas.discard(indice)
        else:
            self._ocultas.add(indice)
        self._agendar()

    def _trocar_aba(self, indice: int) -> None:
        self.paginas.setCurrentIndex(indice)
        self._grupo_abas.button(indice).setChecked(True)

    def _isolar(self, indice: int) -> None:
        for i, linha in self._caixas.items():
            linha.definir(i == indice)
        self._ocultas = set(self._caixas) - {indice}
        self._mostrar_sobre(self._caixas[indice].nome_camada)
        self._agendar()

    def _mostrar_sobre(self, nome: str) -> None:
        texto = ex.camada(nome)
        self.sobre_camada.setText(f"{nome}: {texto}" if texto else "")

    def _filtrar(self, grupo: str | None, trocar: bool = False) -> None:
        nomes = set(ex.grupos_de_camadas().get(grupo, [])) if grupo else None
        for _i, linha in self._caixas.items():
            linha.definir(nomes is None or linha.nome_camada in nomes)
        self._ocultas = {i for i, ln in self._caixas.items() if not ln.visivel}
        indice = [None, "Células", "Fios de sinal", "Alimentação"].index(grupo)
        self._grupo_filtros.button(indice).setChecked(True)
        if trocar:
            self._trocar_aba(0)
        self._agendar()

    # --- inspetor -----------------------------------------------------------------------------

    def _inspecionar(self, x: float, y: float) -> None:
        if self.render is None or self.render.info is None:
            return
        render, raio = self.render, max(0.02, self.prancheta.escala * 3)
        self._trocar_aba(1)
        self._rodar(lambda: render.inspecionar(x, y, raio), self._mostrar_inspecao)

    def _mostrar_inspecao(self, dados: dict) -> None:
        while self._lay_inspetor.count():
            item = self._lay_inspetor.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                item.layout().deleteLater()
        pal = t.paleta()
        self._lay_inspetor.addWidget(
            rotulo(
                f"Ponto x {fmt.numero(dados['x'], 3)} · y {fmt.numero(dados['y'], 3)} µm",
                Papel.MONO,
                "3",
            )
        )
        celulas = dados.get("celulas", [])
        self.prancheta.destaque = tuple(celulas[0]["caixa"]) if celulas else None
        self.prancheta.update()
        if not celulas:
            self._lay_inspetor.addWidget(
                rotulo(
                    "Nenhuma célula aqui: só fios, alimentação ou espaço vazio.", Papel.PEQUENO, "2"
                )
            )
        for c in celulas[:3]:
            explicado = ex.celula(c["celula"])
            familia = c["celula"].split("__")[-1]
            titulo = rotulo(familia, Papel.TITULO)
            self._lay_inspetor.addWidget(titulo)
            if c.get("instancia"):
                self._lay_inspetor.addWidget(rotulo(f"instância {c['instancia']}", Papel.MONO, "2"))
            if explicado:
                texto, forca = explicado
                r = rotulo(texto, Papel.PEQUENO)
                r.setWordWrap(True)
                self._lay_inspetor.addWidget(r)
                if forca:
                    self._lay_inspetor.addWidget(rotulo(forca, Papel.ROTULO, "3"))
            x1, y1, x2, y2 = c["caixa"]
            self._lay_inspetor.addWidget(
                rotulo(f"{fmt.numero(x2 - x1, 2)} × {fmt.numero(y2 - y1, 2)} µm", Papel.MONO, "3")
            )
            completo = rotulo(c["celula"], Papel.MONO, "3")
            completo.setWordWrap(True)
            self._lay_inspetor.addWidget(completo)
        formas = [f for f in dados.get("formas", []) if not f["camada"].startswith("prBoundary")]
        if formas:
            self._lay_inspetor.addWidget(rotulo("Formas neste ponto", Papel.ROTULO, "3"))
            vistas = set()
            for f in formas:
                chave = (f["camada"], f["celula"])
                if chave in vistas:
                    continue
                vistas.add(chave)
                nome = f["camada"].split(" - ")[0]
                linha = rotulo(f"<b>{nome}</b>&nbsp; <span style='color:{pal.tinta_2}'>"
                               f"{f['tipo']} · {f['celula'].split('__')[-1]}</span>",
                               Papel.PEQUENO, rico=True)  # fmt: skip
                linha.setToolTip(ex.camada(nome) or "")
                self._lay_inspetor.addWidget(linha)
        self._lay_inspetor.addStretch(1)

    def _todas(self, visiveis: bool) -> None:
        for linha in self._caixas.values():
            linha.definir(visiveis)
        self._grupo_filtros.button(0).setChecked(True)
        self._ocultas = set() if visiveis else set(self._caixas)
        self._agendar()

    # --- renderização -------------------------------------------------------------------------

    def _agendar(self) -> None:
        if self.render is not None and self.render.info is not None:
            self._temporizador.start()

    def _renderizar(self) -> None:
        if self.render is None or self.render.info is None:
            return
        if self._renderizando:
            self._pendente = True
            return
        self._renderizando = True
        self._pendente = False
        render = self.render
        razao = self.devicePixelRatioF()
        largura = int(self.prancheta.width() * razao)
        altura = int(self.prancheta.height() * razao)
        caixa = self.prancheta.caixa()
        ocultas = set(self._ocultas)
        fundo = t.paleta().fundo

        def desenhar():
            imagem = render.renderizar(largura, altura, caixa, ocultas, fundo)
            return render, QImage(str(imagem.arquivo)), imagem.caixa

        self._rodar(desenhar, self._desenhado, self._falhou_render)

    def _desenhado(self, trio) -> None:
        render, imagem, caixa = trio
        self._renderizando = False
        if render is self.render and not imagem.isNull():
            self.prancheta.definir_imagem(imagem, tuple(caixa))
        if self._pendente:
            self._renderizar()

    def _falhou_render(self, mensagem: str) -> None:
        self._renderizando = False
        self._falhou(mensagem)

    def _falhou(self, mensagem: str) -> None:
        self.aviso.setText("O KLayout da imagem não respondeu; veja o aviso no rodapé.")
        self.sessao.erro.emit(mensagem)

    def _mostrar_cursor(self, x: float, y: float) -> None:
        self.coordenadas.setText(f"x {fmt.numero(x, 3)}   y {fmt.numero(y, 3)} µm")

    def _exportar(self) -> None:
        if self.render is None or self.registro is None:
            return
        sugestao = str(Path.home() / f"layout-{self.registro.numero}.png")
        destino, _ = QFileDialog.getSaveFileName(self, "Exportar layout", sugestao, "PNG (*.png)")
        if not destino:
            return
        render, caixa, ocultas = self.render, self.prancheta.caixa(), set(self._ocultas)
        fundo = t.paleta().fundo

        def exportar() -> str:
            imagem = render.renderizar(3200, int(3200 * self.prancheta.height()
                                                  / max(1, self.prancheta.width())),
                                       caixa, ocultas, fundo)  # fmt: skip
            Path(destino).write_bytes(imagem.arquivo.read_bytes())
            return destino

        self._rodar(exportar, lambda d: self.aviso.setText(f"EXPORTADO: {d}"))

    # --- ciclo de vida ------------------------------------------------------------------------

    def _fechar_render(self) -> None:
        render, self.render = self.render, None
        self.registro = None
        self.prancheta.limpar()
        if render is not None:
            self._rodar(render.encerrar, lambda _x: None, lambda _m: None)

    def encerrar(self) -> None:
        if self.render is not None:
            self.render.encerrar()
            self.render = None


__all__ = ["Prancheta", "QColor", "TelaLayout"]
