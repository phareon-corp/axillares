"""Tela 7 — Ondas: a simulação vista no tempo, dentro do app.

À esquerda, os sinais da onda (por escopo, com busca); no centro, o VisorOndas. A onda vem de uma
execução de simulação ou de teste do projeto. Para quem prefere, "Abrir fora" leva a mesma onda
ao Surfer ou ao GTKWave instalados na máquina.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from axillares.core import formato as fmt
from axillares.core import verificacao
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, SituacaoCaso
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import (
    botao,
    cabecalho_tela,
    layout_de_tela,
    rotulo,
    tom_da_situacao,
)
from axillares.gui.componentes import segmentos as _segmentos
from axillares.gui.sessao import Sessao
from axillares.gui.telas.abertura import CartaoDiagnostico
from axillares.gui.telas.ondas_analise import PainelAnaliseOndas
from axillares.gui.tema import Espaco, Papel
from axillares.gui.visor_ondas import Faixa, VisorOndas, texto_tempo
from axillares.motor.ondas import FATORES_PS, ErroOnda, Onda

PAPEL_SINAL = Qt.ItemDataRole.UserRole
CHAVE_VISUALIZADOR = "ondas/visualizador_externo"
COMO_LER = (
    "Cada linha é um fio do circuito, e o tempo corre para a direita. Um sinal de 1 bit sobe e "
    "desce entre 0 e 1; um barramento mostra o número que carrega (em hexadecimal, decimal ou "
    "binário). Clique para pôr o cursor: os valores ao lado dos nomes passam a ser os daquele "
    "instante. Vermelho é X (valor desconhecido — um registrador sem reset, por exemplo); "
    "amarelo é Z (fio solto)."
)


def _rotulo_execucao(r: RegistroExecucao) -> str:
    texto, _ = tom_da_situacao(r.situacao)
    extra = ""
    passaram, total = r.metrica("testes_passaram"), r.metrica("testes_total")
    if passaram and total:
        extra = f" · {fmt.numero(passaram.valor, 0)}/{fmt.numero(total.valor, 0)} testes"
    return f"#{r.numero} · {r.etapa.value} · {texto}{extra} · {fmt.momento(r.inicio)}"


class TelaOndas(QWidget):
    pedir_execucao = Signal(object)
    """Etapa a executar (sim ou teste), pedida pelo estado vazio."""

    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self._registros: list[RegistroExecucao] = []
        self._pedido: str | None = None
        self.onda: Onda | None = None
        self._config = QSettings("Axillares", "axillares")
        self._tarefas: list[tarefas.Tarefa] = []

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.pilha = QStackedWidget()
        raiz.addWidget(self.pilha)
        self.pilha.addWidget(self._montar_vazio())
        self.pilha.addWidget(self._montar_visor())
        sessao.projeto_mudou.connect(lambda _p: self.recarregar())
        sessao.execucoes_mudaram.connect(self._execucoes_mudaram)
        sessao.execucao_concluida.connect(self._concluida)

    # --- montagem -----------------------------------------------------------------------------

    def _montar_vazio(self) -> QWidget:
        w = QWidget()
        lay = layout_de_tela(w)
        cab, _ = cabecalho_tela(
            "Ondas",
            f"O circuito visto no {t.serifa('tempo', tamanho_px=54)}.",
            "Uma simulação grava como cada sinal muda a cada instante. Rode o testbench "
            "(Simular) para olhar o comportamento, ou os testes automáticos (Testar), que também "
            "deixam a onda para você investigar uma falha.",
        )
        lay.addLayout(cab)
        acoes = QHBoxLayout()
        acoes.setSpacing(Espaco.S + 2)
        simular = botao("Simular  ▸", "primario")
        simular.clicked.connect(lambda: self.pedir_execucao.emit(Etapa.SIMULACAO))
        testar = botao("Testar  ▸", "fantasma")
        testar.clicked.connect(lambda: self.pedir_execucao.emit(Etapa.TESTE))
        acoes.addWidget(simular)
        acoes.addWidget(testar)
        acoes.addStretch(1)
        lay.addLayout(acoes)
        self.aviso_vazio = QVBoxLayout()
        lay.addLayout(self.aviso_vazio)
        lay.addStretch(1)
        return w

    def _montar_visor(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        barra = QFrame()
        barra.setProperty("tipo", "barra-abas")
        b = QHBoxLayout(barra)
        b.setContentsMargins(Espaco.M + 2, 6, Espaco.M, 6)
        b.setSpacing(Espaco.S)
        b.addWidget(rotulo("Ondas", Papel.ROTULO, "3"))
        self.combo = QComboBox()
        self.combo.setFont(t.fonte(Papel.MONO))
        self.combo.setMinimumWidth(240)
        self.combo.currentIndexChanged.connect(self._escolheu)
        b.addWidget(self.combo, 1)
        b.addSpacing(Espaco.S)
        self.bases = {}
        for base, texto in (("hex", "HEX"), ("dec", "DEC"), ("bin", "BIN")):
            botao_base = botao(texto, "compacto")
            botao_base.setCheckable(True)
            botao_base.setToolTip("Como os barramentos mostram o número")
            botao_base.clicked.connect(lambda _c=False, x=base: self._base(x))
            self.bases[base] = botao_base
            b.addWidget(botao_base)
        self.bases["hex"].setChecked(True)
        b.addSpacing(Espaco.S)
        for texto, dica, acao in (
            ("−", "Afastar (−)", lambda: self.visor.zoom(1 / 1.5)),
            ("+", "Aproximar (+ ou Ctrl+roda)", lambda: self.visor.zoom(1.5)),
            ("Ajustar", "Toda a simulação na tela (F)", lambda: self.visor.ajustar()),
        ):
            z = botao(texto, "compacto")
            z.setToolTip(dica)
            z.clicked.connect(acao)
            b.addWidget(z)
        b.addSpacing(Espaco.S)
        alturas, self._grupo_altura = _segmentos(
            [("P", "compacta"), ("M", "normal"), ("G", "grande")], self._altura
        )
        for i, dica in enumerate(("Linhas compactas", "Linhas normais", "Linhas grandes")):
            self._grupo_altura.button(i).setToolTip(dica)
        self._grupo_altura.button(1).setChecked(True)
        b.addLayout(alturas)
        self.botao_analise = botao("Análise", "compacto")
        self.botao_analise.setCheckable(True)
        self.botao_analise.setChecked(True)
        self.botao_analise.setToolTip("Atividade, medição entre cursores e histograma")
        self.botao_analise.toggled.connect(self._alternar_analise)
        b.addWidget(self.botao_analise)
        b.addSpacing(Espaco.S)
        self.combo_fora = QComboBox()
        self.combo_fora.setFont(t.fonte(Papel.PEQUENO))
        self.combo_fora.addItem("Surfer", "surfer")
        self.combo_fora.addItem("GTKWave", "gtkwave")
        preferido = self._config.value(CHAVE_VISUALIZADOR, "surfer")
        self.combo_fora.setCurrentIndex(max(0, self.combo_fora.findData(preferido)))
        self.combo_fora.activated.connect(
            lambda _i: self._config.setValue(CHAVE_VISUALIZADOR, self.combo_fora.currentData())
        )
        self.combo_fora.setToolTip("Visualizador instalado na máquina, para abrir fora do app")
        fora = botao("Abrir fora ↗", "compacto")
        fora.clicked.connect(self.abrir_fora)
        b.addWidget(self.combo_fora)
        b.addWidget(fora)
        col.addWidget(barra)

        self.avisos = QVBoxLayout()
        self.avisos.setContentsMargins(Espaco.M, 0, Espaco.M, 0)
        col.addLayout(self.avisos)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setHandleWidth(1)
        divisor.setChildrenCollapsible(False)
        lateral = QFrame()
        lateral.setProperty("tipo", "lateral-editor")
        lat = QVBoxLayout(lateral)
        lat.setContentsMargins(Espaco.M, Espaco.M, Espaco.M, Espaco.M)
        lat.setSpacing(Espaco.S)
        lat.addWidget(rotulo("Sinais", Papel.ROTULO, "3"))
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("procurar sinal…")
        self.busca.setFont(t.fonte(Papel.MONO))
        self.busca.textChanged.connect(self._filtrar)
        lat.addWidget(self.busca)
        self.arvore = QTreeWidget()
        self.arvore.setHeaderHidden(True)
        self.arvore.setIndentation(Espaco.M)
        self.arvore.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.arvore.itemChanged.connect(self._marcou)
        lat.addWidget(self.arvore, 1)
        self.como_ler = rotulo(COMO_LER, Papel.PEQUENO, "3")
        self.como_ler.setWordWrap(True)
        lat.addWidget(self.como_ler)
        lateral.setMinimumWidth(230)
        divisor.addWidget(lateral)

        miolo = QWidget()
        m = QVBoxLayout(miolo)
        m.setContentsMargins(0, 0, 0, 0)
        m.setSpacing(0)
        self.visor = VisorOndas()
        self.visor.cursor_mudou.connect(self._cursor_mudou)
        self.visor.linha_escolhida.connect(lambda _n: self.analise.atualizar())
        self.visor.menu_da_linha.connect(self._menu_da_linha)
        self.analise = PainelAnaliseOndas(self.visor)
        self.analise.setProperty("tipo", "lateral-editor")
        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setHandleWidth(1)
        vertical.setChildrenCollapsible(False)
        vertical.addWidget(self.visor)
        vertical.addWidget(self.analise)
        vertical.setStretchFactor(0, 1)
        vertical.setSizes([560, 280])
        m.addWidget(vertical, 1)
        estado = QFrame()
        estado.setProperty("tipo", "barra-estado")
        e = QHBoxLayout(estado)
        e.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        self.info = rotulo("", Papel.ETIQUETA, "2")
        e.addWidget(self.info)
        e.addStretch(1)
        atalhos = rotulo("CLIQUE: CURSOR A · SHIFT+CLIQUE: CURSOR B · ARRASTE: MOVER · CTRL+RODA: "
                         "ZOOM · ← →: PRÓXIMA MUDANÇA · BOTÃO DIREITO NO NOME: OPÇÕES",
                         Papel.ETIQUETA, "3")  # fmt: skip
        atalhos.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        atalhos.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        e.addWidget(atalhos, 1)
        estado.setFixedHeight(30)
        m.addWidget(estado)
        divisor.addWidget(miolo)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([270, 1000])
        col.addWidget(divisor, 1)
        return w

    # --- execuções -----------------------------------------------------------------------------

    def recarregar(self) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            self._registros = []
            self.pilha.setCurrentIndex(0)
            return

        def ler() -> list[RegistroExecucao]:
            saida = []
            for r in caderno.listar():
                if r.etapa.verifica:
                    completo = caderno.carregar(r.id)
                    if verificacao.onda(completo) is not None:
                        saida.append(completo)
            return saida

        self._rodar(ler, self._mostrar_lista)

    def _rodar(self, funcao, ao_concluir) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(self.sessao.erro)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    def _execucoes_mudaram(self) -> None:
        if self.isVisible():
            self.recarregar()

    def _concluida(self, registro: RegistroExecucao) -> None:
        if registro.etapa.verifica:
            self._pedido = registro.id
            self.recarregar()

    def _mostrar_lista(self, registros: list[RegistroExecucao]) -> None:
        self._registros = registros
        if not registros:
            self.pilha.setCurrentIndex(0)
            self.onda = None
            return
        self.pilha.setCurrentIndex(1)
        atual = self.combo.currentData()
        alvo = self._pedido or atual or registros[0].id
        self._pedido = None
        self.combo.blockSignals(True)
        self.combo.clear()
        for r in registros:
            self.combo.addItem(_rotulo_execucao(r), r.id)
        indice = max(0, self.combo.findData(alvo))
        self.combo.setCurrentIndex(indice)
        self.combo.blockSignals(False)
        if self.onda is None or alvo != atual:
            self._escolheu(indice)

    def mostrar_execucao(self, ident: str) -> None:
        """Pedido de outra tela ("Ver onda" no detalhe da execução)."""
        indice = self.combo.findData(ident)
        if indice >= 0:
            self.combo.setCurrentIndex(indice)
        else:
            self._pedido = ident
            self.recarregar()

    def mostrar_no(self, nome_no: str) -> None:
        """Pedido da ponteira do layout: o sinal de mesmo nome (q[3] → q) na onda mais recente,
        no topo da lista e escolhido."""
        self._no_pedido = nome_no.split("[")[0]
        if self._registros and self.onda is not None:
            self._aplicar_no()
        else:
            self.recarregar()

    def _aplicar_no(self) -> None:
        base = getattr(self, "_no_pedido", None)
        if not base or self.onda is None:
            return
        self._no_pedido = None
        candidatos = sorted((s for s in self.onda.sinais if s.nome == base),
                            key=lambda s: s.profundidade)  # fmt: skip
        if not candidatos:
            return
        alvo = candidatos[0].nome_completo
        linhas = [alvo] + [x for x in self.visor.linhas if x != alvo]
        self.mostrar_sinais(linhas)
        self.visor.escolhida = 0
        self.visor.update()

    def ao_mostrar(self) -> None:
        if not self._registros:
            self.recarregar()

    @property
    def registro(self) -> RegistroExecucao | None:
        ident = self.combo.currentData()
        return next((r for r in self._registros if r.id == ident), None)

    def _escolheu(self, _indice: int) -> None:
        r = self.registro
        if r is None:
            return
        caminho = verificacao.onda(r)
        if caminho is None:
            return

        def ler() -> tuple[Onda, list[Faixa]]:
            onda = Onda(caminho)
            return onda, self._faixas(r, onda)

        tarefa = tarefas.em_segundo_plano(ler, self)
        tarefa.concluido.connect(lambda par: self._carregada(*par))
        tarefa.falhou.connect(self._falhou)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    @staticmethod
    def _faixas(r: RegistroExecucao, onda: Onda) -> list[Faixa]:
        if r.etapa is not Etapa.TESTE:
            return []
        por_unidade = onda.fator * FATORES_PS.get(onda.unidade, 1.0)
        faixas = []
        for c in verificacao.casos(r):
            if c.inicio_ns is None or c.fim_ns is None or c.situacao is SituacaoCaso.PULADO:
                continue
            faixas.append(Faixa(c.inicio_ns * 1000 / por_unidade, c.fim_ns * 1000 / por_unidade,
                                c.nome, c.situacao is SituacaoCaso.PASSOU))  # fmt: skip
        return faixas

    def _falhou(self, mensagem: str) -> None:
        self._limpar_avisos()
        from axillares.ambiente.diagnostico import Diagnostico

        diagnostico = Diagnostico(
            codigo="onda",
            o_que=mensagem,
            por_que="",
            proximo_passo="Rode a simulação de novo; se persistir, abra a onda fora do app.",
        )
        self.avisos.addWidget(CartaoDiagnostico(diagnostico))

    def _limpar_avisos(self) -> None:
        while self.avisos.count():
            item = self.avisos.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _carregada(self, onda: Onda, faixas: list[Faixa]) -> None:
        self._limpar_avisos()
        self.onda = onda
        iniciais = onda.sinais_iniciais()
        self._preencher_arvore(onda, set(iniciais))
        self.visor.definir(onda, iniciais, faixas)
        self.analise.preparar()
        self._cursor_mudou(None)
        self._aplicar_no()

    # --- sinais --------------------------------------------------------------------------------

    def _preencher_arvore(self, onda: Onda, marcados: set[str]) -> None:
        self.arvore.blockSignals(True)
        self.arvore.clear()
        escopos: dict[str, QTreeWidgetItem] = {}
        for escopo in onda.escopos():
            item = QTreeWidgetItem([escopo.rpartition(".")[2] or escopo])
            item.setFont(0, t.fonte(Papel.ROTULO))
            item.setForeground(0, t.paleta().qcolor("tinta_3"))
            item.setToolTip(0, escopo)
            pai = escopos.get(escopo.rpartition(".")[0])
            (pai.addChild(item) if pai else self.arvore.addTopLevelItem(item))
            escopos[escopo] = item
        for s in onda.sinais:
            largura = f" [{s.largura - 1}:0]" if s.largura > 1 else ""
            item = QTreeWidgetItem([s.nome + largura])
            item.setFont(0, t.fonte(Papel.MONO))
            item.setData(0, PAPEL_SINAL, s.nome_completo)
            item.setToolTip(0, f"{s.nome_completo} · {s.tipo.lower()}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if s.nome_completo in marcados
                               else Qt.CheckState.Unchecked)  # fmt: skip
            escopos[s.escopo].addChild(item)
        self.arvore.expandAll()
        self.arvore.blockSignals(False)

    def _marcou(self, item: QTreeWidgetItem, _coluna: int) -> None:
        nome = item.data(0, PAPEL_SINAL)
        if not nome:
            return
        linhas = list(self.visor.linhas)
        if item.checkState(0) == Qt.CheckState.Checked and nome not in linhas:
            linhas.append(nome)
        elif item.checkState(0) == Qt.CheckState.Unchecked and nome in linhas:
            linhas.remove(nome)
        self.visor.definir_linhas(linhas)
        self.analise.atualizar()

    def mostrar_sinais(self, nomes: list[str]) -> None:
        """Marca exatamente estes sinais (na ordem dada)."""
        iterador = QTreeWidgetItemIterator(self.arvore)
        self.arvore.blockSignals(True)
        while iterador.value():
            item = iterador.value()
            nome = item.data(0, PAPEL_SINAL)
            if nome:
                item.setCheckState(0, Qt.CheckState.Checked if nome in nomes
                                   else Qt.CheckState.Unchecked)  # fmt: skip
            iterador += 1
        self.arvore.blockSignals(False)
        self.visor.definir_linhas(nomes)

    def _filtrar(self, texto: str) -> None:
        procura = texto.strip().lower()
        iterador = QTreeWidgetItemIterator(self.arvore)
        while iterador.value():
            item = iterador.value()
            nome = item.data(0, PAPEL_SINAL)
            if nome:
                item.setHidden(bool(procura) and procura not in nome.lower())
            iterador += 1

    def _base(self, base: str) -> None:
        for chave, b in self.bases.items():
            b.setChecked(chave == base)
        self.visor.definir_base(base)

    def _altura(self, nome: object) -> None:
        self.visor.definir_altura(str(nome))

    def _alternar_analise(self, ligado: bool) -> None:
        self.analise.setVisible(ligado)
        if ligado:
            self.analise.atualizar()

    def _menu_da_linha(self, nome: str, posicao) -> None:
        """Botão direito no nome de um sinal: como desenhar, que cor, tirar da lista."""
        onda = self.onda
        if onda is None:
            return
        sinal = next((s for s in onda.sinais if s.nome_completo == nome), None)
        menu = QMenu(self)
        if sinal is not None and sinal.largura > 1:
            atual = self.visor.modos.get(nome, "digital")
            for modo, texto in (("digital", "Digital (valores)"),
                                ("analogico", "Analógico (curva do número)")):  # fmt: skip
                acao = menu.addAction(texto)
                acao.setCheckable(True)
                acao.setChecked(atual == modo)
                acao.triggered.connect(lambda _c=False, m=modo: self.visor.definir_modo(nome, m))
            menu.addSeparator()
        cores = menu.addMenu("Cor")
        for i in range(len(t.paleta().series)):
            pixmap = QPixmap(14, 14)
            pixmap.fill(t.paleta().serie(i))
            acao = cores.addAction(QIcon(pixmap), f"Cor {i + 1}")
            acao.triggered.connect(lambda _c=False, k=i: self.visor.definir_cor(nome, k))
        menu.addSeparator()
        remover = menu.addAction("Tirar da lista")
        remover.triggered.connect(
            lambda: self.mostrar_sinais([x for x in self.visor.linhas if x != nome])
        )
        menu.exec(posicao)

    def _cursor_mudou(self, tempo: object) -> None:
        self.analise.atualizar()
        onda = self.onda
        if onda is None:
            self.info.setText("")
            return
        total = texto_tempo(onda.em_ps(onda.fim))
        partes = [f"{onda.formato}", f"{len(onda.sinais)} sinais", f"até {total}"]
        if tempo is not None:
            partes.insert(0, f"cursor em {texto_tempo(onda.em_ps(int(tempo)))}")
        self.info.setText("  ·  ".join(partes).upper())

    def abrir_fora(self) -> None:
        r = self.registro
        caminho: Path | None = verificacao.onda(r) if r else None
        if caminho is None:
            return
        from axillares.ambiente.abrir import abrir_onda

        visualizador = self.combo_fora.currentData()
        self._config.setValue(CHAVE_VISUALIZADOR, visualizador)
        diag = abrir_onda(caminho, visualizador)
        self._limpar_avisos()
        if diag is not None:
            self.avisos.addWidget(CartaoDiagnostico(diag))


__all__ = ["ErroOnda", "TelaOndas"]
