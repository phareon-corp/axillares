"""Tela 3 — Editor: arquivos do projeto, abas, Monaco, execução e problemas no mesmo lugar."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from axillares.core import fontes, verificacao
from axillares.core import formato as fmt
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, Local, Situacao
from axillares.core.projeto import Projeto
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.assistente import Assistente, locais_por_arquivo
from axillares.gui.componentes import (
    Pilula,
    Ponto,
    Tabela,
    botao,
    quadro,
    repolir,
    rotulo,
    tom_da_situacao,
)
from axillares.gui.sessao import Sessao
from axillares.gui.telas.estrutura import PainelEstrutura
from axillares.gui.tema import Espaco, Papel
from axillares.motor import linguagem as lg

PAPEL_CAMINHO = Qt.ItemDataRole.UserRole
FONTES_PROBLEMAS = ("fluxo", "verible", "verilator")
NOMES_FONTE = {"fluxo": "execução", "verible": "Verible", "verilator": "Verilator"}
NOMES_LINGUAGEM = {
    "systemverilog": "SystemVerilog",
    "tcl": "Tcl / SDC",
    "python": "Python",
    "markdown": "Markdown",
    "ini": "TOML",
    "shell": "Shell",
    "plaintext": "Texto",
}


PAPEIS = {
    "RTL": ("V", "o circuito"),
    "Testbenches": ("TB", "teste em simulação"),
    "Restrições": ("SDC", "relógio e atrasos"),
    "Projeto": ("TOML", "ficha do projeto"),
    "Outros": ("MD", "documentação"),
}
CONTEXTOS = {
    "RTL": "Este é o circuito, descrito em Verilog. A síntese transforma este texto em portas "
    "lógicas da biblioteca do PDK; o resto do fluxo dá forma física a elas.",
    "Testbenches": "Um testbench é um circuito de mentira que gera estímulos e confere as "
    "respostas do seu circuito em simulação. Não vira chip: serve para descobrir erros antes "
    "da síntese.",
    "Restrições": "As restrições (SDC) dizem ao fluxo qual é o relógio e quanto tempo os sinais "
    "têm nas bordas do chip. A análise de temporização usa este arquivo para dizer se o "
    "circuito cabe.",
    "Projeto": "O axil.toml é a ficha do projeto: qual é o módulo de topo, onde estão as fontes, o "
    "PDK, a frequência alvo e que motor executa cada etapa.",
    "Outros": "Um arquivo de apoio do projeto.",
}


class ItemArquivo(QWidget):
    """Linha da árvore: etiqueta do tipo, nome e papel do arquivo no fluxo."""

    def __init__(self, nome: str, grupo: str) -> None:
        super().__init__()
        sigla, papel = PAPEIS.get(grupo, ("•", ""))
        if sigla == "V" and nome.lower().endswith((".sv", ".svh")):
            sigla = "SV"
        elif sigla == "TB" and nome.lower().endswith(".py"):
            sigla, papel = "PY", "teste automático (cocotb)"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.setFixedHeight(46)
        lay.setSpacing(Espaco.S + 2)
        self.sigla = rotulo(sigla, Papel.ETIQUETA, "2")
        self.sigla.setProperty("tipo", "sigla")
        self.sigla.setFixedWidth(38)
        self.sigla.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.sigla, 0, Qt.AlignmentFlag.AlignVCenter)
        coluna = QVBoxLayout()
        coluna.setSpacing(1)
        self.nome = rotulo(nome, Papel.PEQUENO)
        coluna.addWidget(self.nome)
        if papel:
            self.papel = rotulo(papel, Papel.PEQUENO, "3")
            coluna.addWidget(self.papel)
        lay.addLayout(coluna, 1)
        self.marca = rotulo("", Papel.ETIQUETA, "acento")
        lay.addWidget(self.marca, 0, Qt.AlignmentFlag.AlignVCenter)

    def definir(self, sujo: bool, problemas: int, atual: bool) -> None:
        if problemas:
            self.marca.setText(f"✕ {problemas}")
            self.marca.setProperty("tom", "falha")
        else:
            self.marca.setText("●" if sujo else "")
            self.marca.setProperty("tom", "acento")
        self.nome.setProperty("tom", "falha" if problemas else (None if atual else "2"))
        for w in (self.marca, self.nome):
            w.style().unpolish(w)
            w.style().polish(w)


class Aba(QFrame):
    clicada = Signal(Path)
    fechar = Signal(Path)

    def __init__(self, caminho: Path, rotulo_texto: str) -> None:
        super().__init__()
        self.caminho = caminho
        self.setProperty("tipo", "aba")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Espaco.M - 2, 0, 6, 0)
        lay.setSpacing(6)
        self.ponto = Ponto(5, "acento")
        self.ponto.hide()
        self.nome = rotulo(rotulo_texto, Papel.PEQUENO)
        self.botao_fechar = QPushButton("×")
        self.botao_fechar.setProperty("tipo", "fechar-aba")
        self.botao_fechar.setFixedSize(20, 20)
        self.botao_fechar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_fechar.clicked.connect(lambda: self.fechar.emit(self.caminho))
        lay.addWidget(self.nome)
        lay.addWidget(self.ponto)
        lay.addWidget(self.botao_fechar)
        self.setFixedHeight(38)

    def definir(self, ativa: bool, suja: bool) -> None:
        self.setProperty("ativa", "sim" if ativa else "nao")
        self.nome.setProperty("tom", None if ativa else "2")
        self.ponto.setVisible(suja)
        for w in (self, self.nome):
            w.style().unpolish(w)
            w.style().polish(w)

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicada.emit(self.caminho)
        elif evento.button() == Qt.MouseButton.MiddleButton:
            self.fechar.emit(self.caminho)


class TelaEditor(QWidget):
    sujos_mudaram = Signal(bool)

    def __init__(
        self,
        sessao: Sessao,
        fabrica_editor: Callable[[], QWidget] | None = None,
        fabrica_assistente: Callable[[], Assistente] | None = None,
    ) -> None:
        super().__init__()
        self.sessao = sessao
        self._fabrica_editor = fabrica_editor
        self.assistente = (fabrica_assistente or Assistente)()
        self.assistente.setParent(self)
        self._assistente_ligado = False
        self.editor = None  # criado na primeira vez que a tela aparece
        self.abas: dict[Path, Aba] = {}
        self.sujos: set[Path] = set()
        self.atual: Path | None = None
        self._textos: dict[Path, str] = {}
        self._pendentes_ao_abrir: list[tuple[Path, int, int]] = []
        # problemas por fonte: a execução (fluxo), o Verible (ao digitar) e o Verilator (ao salvar)
        self._fontes: dict[str, dict[Path, list[Local]]] = {f: {} for f in FONTES_PROBLEMAS}
        self._gerais: list[str] = []
        self._ocultos: set[Path] = set()  # carregados no Monaco sem aba (para espiar definições)
        self._salvando: set[Path] = set()
        self._seguir_depois_de_salvar: Callable[[], None] | None = None
        self._tarefas: list[tarefas.Tarefa] = []
        self._vigia = QFileSystemWatcher(self)
        self._vigia.fileChanged.connect(self._mudou_no_disco)

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setHandleWidth(1)
        divisor.setChildrenCollapsible(False)
        raiz.addWidget(divisor)

        # --- árvore de arquivos ---
        lateral = QFrame()
        lateral.setProperty("tipo", "lateral-editor")
        lat = QVBoxLayout(lateral)
        lat.setContentsMargins(0, Espaco.L, 0, Espaco.M)
        lat.setSpacing(Espaco.S)
        cabeca = QVBoxLayout()
        cabeca.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        cabeca.setSpacing(2)
        linha_cabeca = QHBoxLayout()
        linha_cabeca.addWidget(rotulo("Arquivos", Papel.ROTULO, "3"))
        linha_cabeca.addStretch(1)
        self.botao_novo = botao("+ Arquivo", "link")
        self.botao_novo.setFont(t.fonte(Papel.ETIQUETA))
        self.botao_novo.setToolTip("Criar um módulo ou testbench (.v ou .sv) com esqueleto")
        self.botao_novo.clicked.connect(self.novo_arquivo)
        linha_cabeca.addWidget(self.botao_novo)
        cabeca.addLayout(linha_cabeca)
        self.nome_projeto = rotulo("", Papel.TITULO)
        cabeca.addWidget(self.nome_projeto)
        lat.addLayout(cabeca)
        self.arvore = QTreeWidget()
        self.arvore.setHeaderHidden(True)
        self.arvore.setRootIsDecorated(False)
        self.arvore.setIndentation(Espaco.M)
        self.arvore.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.arvore.itemClicked.connect(self._clicou_item)
        lat.addWidget(self.arvore, 1)
        self.estrutura = PainelEstrutura()
        self.estrutura.ir.connect(lambda lin, col: self.atual and self.abrir(self.atual, lin, col))
        coluna_lateral = QSplitter(Qt.Orientation.Vertical)
        coluna_lateral.setHandleWidth(1)
        coluna_lateral.setChildrenCollapsible(False)
        coluna_lateral.addWidget(lateral)
        coluna_lateral.addWidget(self.estrutura)
        coluna_lateral.setSizes([520, 300])
        coluna_lateral.setMinimumWidth(240)
        divisor.addWidget(coluna_lateral)

        # --- área do editor ---
        area = QWidget()
        col = QVBoxLayout(area)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        barra = QFrame()
        barra.setProperty("tipo", "barra-abas")
        b = QHBoxLayout(barra)
        b.setContentsMargins(0, 0, Espaco.M, 0)
        b.setSpacing(0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setFixedHeight(38)
        faixa = QWidget()
        self._lay_abas = QHBoxLayout(faixa)
        self._lay_abas.setContentsMargins(0, 0, 0, 0)
        self._lay_abas.setSpacing(0)
        self._lay_abas.addStretch(1)
        rolagem.setWidget(faixa)
        b.addWidget(rolagem, 1)
        self.botao_salvar = botao("Salvar  Ctrl+S", "compacto")
        self.botao_salvar.setToolTip("Ctrl+S")
        self.botao_salvar.clicked.connect(lambda: self.editor and self.editor.salvar())
        self.botao_formatar = botao("Formatar", "compacto")
        self.botao_formatar.setToolTip(
            "Shift+Alt+F — reorganiza recuos e alinhamentos pelo Verible, sem mudar o circuito"
        )
        self.botao_formatar.clicked.connect(
            lambda: self.editor and self.editor.acao("editor.action.formatDocument")
        )
        self.botao_formatar.setEnabled(False)
        self.botao_simular = botao("Simular  ▸", "compacto")
        self.botao_simular.setToolTip("F5 — salva tudo, roda o testbench e grava a onda")
        self.botao_simular.clicked.connect(lambda: self.sessao.executar(Etapa.SIMULACAO))
        self.botao_testar = botao("Testar  ▸", "compacto")
        self.botao_testar.setToolTip("Shift+F5 — salva tudo e roda os testes cocotb")
        self.botao_testar.clicked.connect(lambda: self.sessao.executar(Etapa.TESTE))
        self.botao_sintese = botao("Síntese  ▸", "compacto")
        self.botao_sintese.setMinimumWidth(96)
        self.botao_sintese.setToolTip("Ctrl+Enter — salva tudo e executa a síntese")
        self.botao_sintese.clicked.connect(lambda: self.sessao.executar(Etapa.SINTESE))
        self.botao_gds = botao("GDS  ▸", "compacto-primario")
        self.botao_gds.setMinimumWidth(80)
        self.botao_gds.setToolTip("Ctrl+Shift+Enter — salva tudo e executa o fluxo até o GDS")
        self.botao_gds.clicked.connect(lambda: self.sessao.executar(Etapa.GDS))
        for w in (self.botao_formatar, self.botao_salvar, self.botao_simular, self.botao_testar,
                  self.botao_sintese, self.botao_gds):  # fmt: skip
            b.addSpacing(6)
            b.addWidget(w)
        col.addWidget(barra)

        faixa_contexto = QFrame()
        faixa_contexto.setProperty("tipo", "faixa-contexto")
        fc = QHBoxLayout(faixa_contexto)
        fc.setContentsMargins(Espaco.M + 2, Espaco.S, Espaco.M, Espaco.S)
        fc.setSpacing(Espaco.M)
        coluna_ctx = QVBoxLayout()
        coluna_ctx.setSpacing(3)
        self.caminho = rotulo("", Papel.ETIQUETA, "3")
        coluna_ctx.addWidget(self.caminho)
        self.contexto = rotulo("", Papel.PEQUENO, "2")
        self.contexto.setWordWrap(True)
        coluna_ctx.addWidget(self.contexto)
        fc.addLayout(coluna_ctx, 1)
        self.botao_como = botao("Como funciona o fluxo →", "link")
        self.botao_como.setFont(t.fonte(Papel.ETIQUETA))
        self.botao_como.clicked.connect(lambda: self.sessao.pedir_tela.emit("como-funciona", None))
        fc.addWidget(self.botao_como, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(faixa_contexto)

        self._lugar_editor = QVBoxLayout()
        self._lugar_editor.setContentsMargins(0, 0, 0, 0)
        col.addLayout(self._lugar_editor, 1)

        # --- problemas ---
        self.painel_problemas = quadro("painel-problemas")
        pp = QVBoxLayout(self.painel_problemas)
        pp.setContentsMargins(Espaco.M + 2, Espaco.S + 2, Espaco.M, Espaco.S)
        pp.setSpacing(4)
        topo = QHBoxLayout()
        self.titulo_problemas = rotulo("Problemas", Papel.ROTULO, "2")
        topo.addWidget(self.titulo_problemas)
        topo.addStretch(1)
        ocultar = botao("Ocultar", "link")
        ocultar.setFont(t.fonte(Papel.ETIQUETA))
        ocultar.clicked.connect(self.painel_problemas.hide)
        topo.addWidget(ocultar)
        pp.addLayout(topo)
        self.tabela_problemas = Tabela(
            [("", 1, "e"), ("arquivo", 4, "e"), ("linha", 1, "d"), ("mensagem", 14, "e"),
             ("fonte", 3, "e")],
            [Papel.CORPO, Papel.MONO, Papel.MONO, Papel.PEQUENO, Papel.ETIQUETA],
        )  # fmt: skip
        pp.addWidget(self.tabela_problemas)
        self.painel_problemas.hide()
        col.addWidget(self.painel_problemas)

        # --- barra de estado ---
        estado = QFrame()
        estado.setProperty("tipo", "barra-estado")
        e = QHBoxLayout(estado)
        e.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        e.setSpacing(Espaco.M)
        self.ponto_execucao = Ponto(6, "tinta_3", pulsar=True)
        self.estado_execucao = rotulo("pronto", Papel.ETIQUETA, "2")
        self.estado_execucao.setTextFormat(Qt.TextFormat.PlainText)
        e.addWidget(self.ponto_execucao)
        e.addWidget(self.estado_execucao)
        self.pilula = Pilula("", "tinta_3")
        self.pilula.hide()
        e.addWidget(self.pilula)
        self.ver_execucao = botao("Ver execução →", "link")
        self.ver_execucao.setFont(t.fonte(Papel.ETIQUETA))
        self.ver_execucao.hide()
        e.addWidget(self.ver_execucao)
        self.ver_onda = botao("Ver onda →", "link")
        self.ver_onda.setFont(t.fonte(Papel.ETIQUETA))
        self.ver_onda.hide()
        e.addWidget(self.ver_onda)
        e.addStretch(1)
        self.botao_problemas = botao("", "link")
        self.botao_problemas.setFont(t.fonte(Papel.ETIQUETA))
        self.botao_problemas.setToolTip("Mostrar ou ocultar a lista de problemas")
        self.botao_problemas.clicked.connect(self._alternar_problemas)
        e.addWidget(self.botao_problemas)
        self.estado_lint = rotulo("", Papel.ETIQUETA, "3")
        e.addWidget(self.estado_lint)
        self.ponto_ls = Ponto(6, "tinta_3")
        self.estado_ls = rotulo("", Papel.ETIQUETA, "3")
        e.addWidget(self.ponto_ls)
        e.addWidget(self.estado_ls)
        self.posicao = rotulo("", Papel.ETIQUETA, "2")
        self.linguagem = rotulo("", Papel.ETIQUETA, "2")
        self.situacao_arquivo = rotulo("", Papel.ETIQUETA, "2")
        for w in (self.situacao_arquivo, self.posicao, self.linguagem):
            e.addWidget(w)
        e.addWidget(rotulo("UTF-8", Papel.ETIQUETA, "3"))
        estado.setFixedHeight(30)
        col.addWidget(estado)
        divisor.addWidget(area)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([290, 1000])

        self._inicio = 0.0
        self._ultimo: RegistroExecucao | None = None
        self._passo = ""
        self._relogio = QTimer(self)
        self._relogio.setInterval(200)
        self._relogio.timeout.connect(self._tique)
        self.ver_execucao.clicked.connect(
            lambda: self._ultimo and self.sessao.pedir_tela.emit("execucao", self._ultimo.id)
        )
        self.ver_onda.clicked.connect(
            lambda: self._ultimo and self.sessao.pedir_tela.emit("onda", self._ultimo.id)
        )

        sessao.projeto_mudou.connect(self._projeto_mudou)
        sessao.execucao_iniciada.connect(self._execucao_iniciada)
        sessao.execucao_linha.connect(self._execucao_linha)
        sessao.execucao_concluida.connect(self._execucao_concluida)
        sessao.antes_de_executar = self._salvar_e_seguir

        self._tabela_pendente = QTimer(self)
        self._tabela_pendente.setSingleShot(True)
        self._tabela_pendente.setInterval(250)
        self._tabela_pendente.timeout.connect(self._preencher_problemas)
        self._estrutura_pendente = QTimer(self)
        self._estrutura_pendente.setSingleShot(True)
        self._estrutura_pendente.setInterval(350)
        self._estrutura_pendente.timeout.connect(self._pedir_estrutura)
        self.assistente.diagnosticos.connect(self._diagnosticos)
        self.assistente.lint_pronto.connect(self._lint_pronto)
        self.assistente.estado_linguagem.connect(self._estado_linguagem)
        self.assistente.estado_lint.connect(self._estado_lint)
        self._mostrar_vazio()
        self._atualizar_contagem()

    # --- ciclo de vida ------------------------------------------------------------------------

    def showEvent(self, evento: QShowEvent) -> None:
        self.garantir_editor()
        super().showEvent(evento)

    def garantir_editor(self) -> None:
        if self.editor is not None:
            return
        if self._fabrica_editor is not None:
            self.editor = self._fabrica_editor()
        else:
            from axillares.gui.editor.widget import EditorCodigo

            self.editor = EditorCodigo()
        self.editor.sujo_mudou.connect(self._sujo_mudou)
        self.editor.cursor_mudou.connect(self._cursor_mudou)
        self.editor.salvar_pedido.connect(self._salvar)
        self.editor.acao_pedida.connect(lambda nome: self.sessao.executar(Etapa(nome)))
        if hasattr(self.editor, "texto_mudou"):
            self.editor.texto_mudou.connect(self.assistente.mudar)
            self.editor.pedido_linguagem.connect(self._pedido_linguagem)
            self.editor.abrir_em.connect(lambda c, lin, col: self.abrir(c, lin, col))
        self._lugar_editor.addWidget(self.editor)
        self._ligar_assistente()

    def _ligar_assistente(self) -> None:
        """O servidor de linguagem e o lint sobem na primeira vez que o editor aparece."""
        if not self._assistente_ligado:
            self._assistente_ligado = True
            self.assistente.definir_projeto(self.sessao.projeto)

    def encerrar(self) -> None:
        self.assistente.encerrar()

    def _rodar(self, funcao, ao_concluir) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(self.sessao.erro)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    # --- projeto e árvore ---------------------------------------------------------------------

    def _projeto_mudou(self, projeto: Projeto | None) -> None:
        anterior = getattr(self, "_raiz", None)
        self._raiz = projeto.raiz if projeto is not None else None
        if projeto is not None and projeto.raiz == anterior:
            # o mesmo projeto relido (arquivo novo, placa trocada): abas e edições ficam
            self.nome_projeto.setText(projeto.nome)
            if self._assistente_ligado:
                self.assistente.projeto = projeto
                self.assistente.reiniciar()
                self.assistente.conferir(agora=True)
            self.recarregar_arvore()
            return
        for caminho in list(self.abas):
            self._fechar(caminho, forcar=True)
        for caminho in list(self._ocultos):
            if self.editor is not None:
                self.editor.fechar(caminho)
        self._ocultos.clear()
        for fonte in self._fontes.values():
            fonte.clear()
        self._gerais = []
        self.painel_problemas.hide()
        self._atualizar_contagem()
        self.arvore.clear()
        if self._assistente_ligado:
            self.assistente.definir_projeto(projeto)
        if projeto is None:
            self._mostrar_vazio()
            return
        self.nome_projeto.setText(projeto.nome)
        self._rodar(lambda: fontes.agrupar(projeto), self._preencher_arvore)

    def recarregar_arvore(self) -> None:
        projeto = self.sessao.projeto
        if projeto is not None:
            self._rodar(lambda: fontes.agrupar(projeto), self._preencher_arvore)

    def _preencher_arvore(self, grupos: list[fontes.Grupo]) -> None:
        self.arvore.clear()
        self._itens: dict[Path, ItemArquivo] = {}
        self._grupo_de: dict[Path, str] = {}
        projeto = self.sessao.projeto
        for g in grupos:
            topo = QTreeWidgetItem([g.nome.upper()])
            topo.setFont(0, t.fonte(Papel.ROTULO))
            topo.setFlags(Qt.ItemFlag.ItemIsEnabled)
            topo.setForeground(0, t.paleta().qcolor("tinta_3"))
            self.arvore.addTopLevelItem(topo)
            for arquivo in g.arquivos:
                rel = projeto.relativo(arquivo) if projeto else arquivo.name
                item = QTreeWidgetItem([""])
                item.setToolTip(0, rel)
                item.setData(0, PAPEL_CAMINHO, str(arquivo))
                topo.addChild(item)
                widget = ItemArquivo(arquivo.name, g.nome)
                widget.setToolTip(rel)
                item.setSizeHint(0, QSize(200, 46))
                self.arvore.setItemWidget(item, 0, widget)
                self._itens[arquivo] = widget
                self._grupo_de[arquivo] = g.nome
            topo.setExpanded(True)
        self._marcar_arvore()
        recem_criado = getattr(self, "_abrir_depois", None)
        if recem_criado is not None:
            self._abrir_depois = None
            self.abrir(recem_criado)
            return
        # ao abrir um projeto, o RTL principal já aparece aberto
        if not self.abas and projeto is not None:
            topo_rtl = next(
                (a for a in projeto.arquivos_rtl() if a.stem == projeto.projeto.topo),
                next(iter(projeto.arquivos_rtl()), None),
            )
            if topo_rtl is not None:
                self.abrir(topo_rtl)

    def problemas_de(self, caminho: Path) -> list[Local]:
        return [x for fonte in self._fontes.values() for x in fonte.get(caminho, [])]

    @property
    def _problemas(self) -> dict[Path, list[Local]]:
        """Todos os problemas, de todas as fontes, por arquivo."""
        caminhos = {c for fonte in self._fontes.values() for c in fonte}
        return {c: self.problemas_de(c) for c in caminhos if self.problemas_de(c)}

    def _marcar_arvore(self) -> None:
        for caminho, widget in getattr(self, "_itens", {}).items():
            erros = sum(1 for x in self.problemas_de(caminho) if x.gravidade == "erro")
            widget.definir(caminho in self.sujos, erros, caminho == self.atual)

    def _clicou_item(self, item: QTreeWidgetItem) -> None:
        dado = item.data(0, PAPEL_CAMINHO)
        if dado:
            self.abrir(Path(dado))

    # --- abrir, abas, fechar ------------------------------------------------------------------

    def abrir(self, caminho: Path, linha: int = 0, coluna: int = 1) -> None:
        self.garantir_editor()
        projeto = self.sessao.projeto
        if projeto is None:
            return
        if caminho in self.abas:
            self._ativar(caminho)
            if linha:
                self.editor.ir_para(caminho, linha, coluna)
            return
        if linha:
            self._pendentes_ao_abrir.append((caminho, linha, coluna))
        self._rodar(lambda: (caminho, fontes.ler(projeto, caminho)), self._aberto)

    def _criar_aba(self, caminho: Path, texto: str) -> None:
        aba = Aba(caminho, caminho.name)
        aba.clicada.connect(self._ativar)
        aba.fechar.connect(self._fechar)
        self._lay_abas.insertWidget(self._lay_abas.count() - 1, aba)
        self.abas[caminho] = aba
        self._textos[caminho] = texto
        self._ocultos.discard(caminho)
        if str(caminho) not in self._vigia.files():
            self._vigia.addPath(str(caminho))
        self.assistente.abrir(caminho, texto)

    def _aberto(self, par: tuple[Path, str]) -> None:
        caminho, texto = par
        if caminho not in self.abas:
            self._criar_aba(caminho, texto)
            self.editor.abrir(caminho, texto)
            for fonte in FONTES_PROBLEMAS:
                if self._fontes[fonte].get(caminho):
                    self.editor.problemas(caminho, self._fontes[fonte][caminho], fonte)
        self._ativar(caminho)
        for pendente in [p for p in self._pendentes_ao_abrir if p[0] == caminho]:
            self._pendentes_ao_abrir.remove(pendente)
            self.editor.ir_para(*pendente)

    def _ativar(self, caminho: Path) -> None:
        if caminho not in self.abas:
            return
        if caminho != self.atual:
            self.editor.abrir(caminho, self._textos.get(caminho, ""))
        self.atual = caminho
        projeto = self.sessao.projeto
        rel = projeto.relativo(caminho) if projeto else caminho.name
        self.caminho.setText(f"{projeto.nome if projeto else ''} / {rel}")
        grupo = getattr(self, "_grupo_de", {}).get(caminho, "Outros")
        contexto = CONTEXTOS.get(grupo, "")
        if caminho.suffix.lower() in {".sv", ".svh"}:
            contexto = contexto.replace("em Verilog", "em SystemVerilog")
        self.contexto.setText(contexto)
        self._atualizar_abas()
        self._atualizar_ferramentas()
        self._estrutura_pendente.start()

    def _atualizar_abas(self) -> None:
        for caminho, aba in self.abas.items():
            aba.definir(caminho == self.atual, caminho in self.sujos)
        self.sujos_mudaram.emit(bool(self.sujos))
        self.situacao_arquivo.setText(
            "NÃO SALVO" if self.atual in self.sujos else ("SALVO" if self.atual else "")
        )
        self._marcar_arvore()

    def _fechar(self, caminho: Path, forcar: bool = False) -> None:
        if caminho in self.sujos and not forcar:
            # nunca perde trabalho: salva e fecha
            self._salvando.add(caminho)
            self.editor.salvar(caminho)
            QTimer.singleShot(400, lambda: self._fechar(caminho, forcar=True))
            return
        aba = self.abas.pop(caminho, None)
        if aba is not None:
            aba.deleteLater()
        self.sujos.discard(caminho)
        self._textos.pop(caminho, None)
        self.assistente.fechar(caminho)
        if self._fontes["verible"].pop(caminho, None) is not None:
            self._tabela_pendente.start()
        if str(caminho) in self._vigia.files():
            self._vigia.removePath(str(caminho))
        if self.editor is not None:
            self.editor.fechar(caminho)
        if self.atual == caminho:
            self.atual = None
            restantes = list(self.abas)
            if restantes:
                self._ativar(restantes[-1])
            else:
                self._mostrar_vazio()
        self._atualizar_abas()

    def _mostrar_vazio(self) -> None:
        self.estrutura.mensagem("Abra um arquivo Verilog para ver a estrutura.")
        self.botao_formatar.setEnabled(False)
        self.caminho.setText("")
        self.contexto.setText("Escolha um arquivo à esquerda. Cada um tem um papel no fluxo.")
        self.posicao.setText("")
        self.linguagem.setText("")
        self.situacao_arquivo.setText("")

    # --- gravar -------------------------------------------------------------------------------

    def _sujo_mudou(self, caminho: Path, sujo: bool) -> None:
        if sujo and caminho not in self.abas and caminho in self._ocultos:
            self._criar_aba(caminho, self._textos.get(caminho, ""))
        if sujo:
            self.sujos.add(caminho)
        else:
            self.sujos.discard(caminho)
        self._atualizar_abas()

    def _cursor_mudou(self, linha: int, coluna: int, linguagem: str) -> None:
        self.posicao.setText(f"LN {linha}, COL {coluna}")
        self.linguagem.setText(NOMES_LINGUAGEM.get(linguagem, linguagem))

    def _salvar(self, caminho: Path, texto: str, versao: int) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        self._salvando.add(caminho)

        def gravar() -> tuple[Path, str, int]:
            fontes.salvar(projeto, caminho, texto)
            return caminho, texto, versao

        tarefa = tarefas.em_segundo_plano(gravar, self)
        tarefa.concluido.connect(self._salvo)
        tarefa.falhou.connect(
            lambda msg: (self._salvando.discard(caminho), self.sessao.erro.emit(msg))
        )
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    def _salvo(self, trio: tuple[Path, str, int]) -> None:
        caminho, texto, versao = trio
        self._textos[caminho] = texto
        self._salvando.discard(caminho)
        if self.editor is not None:
            self.editor.marcar_salvo(caminho, versao)
        self.sujos.discard(caminho)
        self._atualizar_abas()
        if self.assistente.e_hdl(caminho):
            self.assistente.conferir()
        if self._seguir_depois_de_salvar and not self._salvando:
            seguir, self._seguir_depois_de_salvar = self._seguir_depois_de_salvar, None
            seguir()

    def _salvar_e_seguir(self, seguir: Callable[[], None]) -> None:
        """Gancho da sessão: antes de executar, grava o que estiver pendente."""
        if not self.sujos or self.editor is None:
            seguir()
            return
        self._seguir_depois_de_salvar = seguir
        self._salvando |= set(self.sujos)
        self.editor.salvar_todos()
        QTimer.singleShot(5000, self._seguir_mesmo_assim)

    def _seguir_mesmo_assim(self) -> None:
        if self._seguir_depois_de_salvar:
            self.sessao.erro.emit("Nem todos os arquivos foram salvos a tempo; executando assim.")
            seguir, self._seguir_depois_de_salvar = self._seguir_depois_de_salvar, None
            seguir()

    def _mudou_no_disco(self, caminho_str: str) -> None:
        caminho = Path(caminho_str)
        if caminho not in self.abas or caminho in self.sujos or caminho in self._salvando:
            return
        projeto = self.sessao.projeto
        if projeto is None or not caminho.exists():
            return
        if caminho_str not in self._vigia.files():  # rename atômico remove o vigia
            self._vigia.addPath(caminho_str)

        def reler() -> tuple[Path, str]:
            return caminho, fontes.ler(projeto, caminho)

        def aplicar(par: tuple[Path, str]) -> None:
            c, texto = par
            if texto != self._textos.get(c) and c not in self.sujos:
                self._textos[c] = texto
                self.editor.recarregar(c, texto)

        self._rodar(reler, aplicar)

    # --- execução -----------------------------------------------------------------------------

    def _execucao_iniciada(self, etapa: Etapa, motor: str) -> None:
        self._inicio = time.monotonic()
        self._passo = f"{etapa.value} · preparando"
        self.ponto_execucao.definir_token("acento")
        self.pilula.hide()
        self.ver_execucao.hide()
        self.ver_onda.hide()
        for b in (self.botao_simular, self.botao_testar, self.botao_sintese, self.botao_gds):
            b.setEnabled(False)
        self._relogio.start()
        self._tique()

    def _execucao_linha(self, _linha: str, passo: str | None) -> None:
        if passo:
            self._passo = passo

    def _tique(self) -> None:
        decorrido = fmt.duracao(time.monotonic() - self._inicio)
        self.estado_execucao.setText(f"{self._passo}   {decorrido}")

    def _execucao_concluida(self, r: RegistroExecucao) -> None:
        self._relogio.stop()
        self._ultimo = r
        for b in (self.botao_simular, self.botao_testar, self.botao_sintese, self.botao_gds):
            b.setEnabled(True)
        self.ver_onda.setVisible(verificacao.onda(r) is not None)
        texto, token = tom_da_situacao(r.situacao)
        self.ponto_execucao.definir_token(token)
        self.pilula.definir(texto, token)
        self.pilula.show()
        self.ver_execucao.show()
        resumo = f"#{r.numero} {r.etapa.value} · {fmt.duracao(r.duracao_s)}"
        m = r.metrica("fmax_mhz")
        if m and r.situacao is Situacao.SUCESSO:
            resumo += f" · Fmax {fmt.numero(m.valor, 1)} MHz"
        passaram, total = r.metrica("testes_passaram"), r.metrica("testes_total")
        if passaram and total:
            resumo += f" · {fmt.numero(passaram.valor, 0)}/{fmt.numero(total.valor, 0)} testes"
        self.estado_execucao.setText(resumo)
        locais = r.falha.locais if r.falha else []
        self.mostrar_problemas(locais)

    def mostrar_problemas(self, locais: list[Local]) -> None:
        """Problemas de uma execução (fluxo): abre o painel e leva ao primeiro."""
        projeto = self.sessao.projeto
        if projeto is None:
            return
        self._definir_fonte("fluxo", locais_por_arquivo(projeto.raiz, locais))
        if not locais:
            return
        self.painel_problemas.show()
        primeiro = locais[0]
        self.abrir((projeto.raiz / primeiro.arquivo).resolve(), primeiro.linha, primeiro.coluna)

    def _definir_fonte(
        self, fonte: str, por_arquivo: dict[Path, list[Local]], so: Path | None = None
    ) -> None:
        """Troca os problemas de uma fonte (todos, ou só de um arquivo) e repinta o que mudou."""
        atual = self._fontes[fonte]
        if so is not None:
            mudaram = {so}
            if por_arquivo.get(so):
                atual[so] = por_arquivo[so]
            else:
                atual.pop(so, None)
        else:
            mudaram = set(atual) | set(por_arquivo)
            self._fontes[fonte] = atual = {c: x for c, x in por_arquivo.items() if x}
        if self.editor is not None:
            for caminho in mudaram:
                if caminho in self.abas:
                    self.editor.problemas(caminho, atual.get(caminho, []), fonte)
        self._marcar_arvore()
        self._atualizar_contagem()
        self._tabela_pendente.start()

    def _todos_os_problemas(self) -> list[tuple[str, Local]]:
        todos = [(f, x) for f in FONTES_PROBLEMAS for lista in self._fontes[f].values()
                 for x in lista]  # fmt: skip
        todos.sort(key=lambda p: (p[1].gravidade != "erro", p[1].arquivo, p[1].linha))
        return todos

    def _atualizar_contagem(self) -> None:
        todos = self._todos_os_problemas()
        erros = sum(1 for _, x in todos if x.gravidade == "erro") + len(self._gerais)
        avisos = len(todos) + len(self._gerais) - erros
        if not erros and not avisos:
            self.painel_problemas.hide()
            self.botao_problemas.setText("✓ sem problemas")
        else:
            self.botao_problemas.setText(f"✕ {erros}   ! {avisos}")
        self.botao_problemas.setProperty("tom", "falha" if erros else ("aviso" if avisos else "ok"))
        repolir(self.botao_problemas)

    def _alternar_problemas(self) -> None:
        if self.painel_problemas.isVisible():
            self.painel_problemas.hide()
        else:
            self._preencher_problemas()
            self.painel_problemas.show()

    def _preencher_problemas(self) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        todos = self._todos_os_problemas()
        erros = sum(1 for _, x in todos if x.gravidade == "erro") + len(self._gerais)
        self.titulo_problemas.setText(
            f"PROBLEMAS · {erros} ERRO(S) · {len(todos) + len(self._gerais) - erros} AVISO(S)"
        )
        self.tabela_problemas.limpar()
        for geral in self._gerais:
            marca = rotulo("✕", Papel.CORPO_FORTE, "falha")
            self.tabela_problemas.adicionar([marca, "—", "", geral, "Verilator"],
                                            tons=[None, "3", "3", None, "3"])  # fmt: skip
        for fonte, local in todos[:300]:
            caminho = (projeto.raiz / local.arquivo).resolve()
            erro = local.gravidade == "erro"
            marca = rotulo("✕" if erro else "!", Papel.CORPO_FORTE, "falha" if erro else "aviso")
            codigo = local.origem.partition(" · ")[2]
            nome_fonte = NOMES_FONTE[fonte] + (f" · {codigo}" if codigo else "")
            self.tabela_problemas.adicionar(
                [marca, local.arquivo, str(local.linha), local.mensagem, nome_fonte],
                ao_clicar=lambda c=caminho, x=local: self.abrir(c, x.linha, x.coluna),
                tons=[None, "2", "2", None, "3"],
            )
        if not todos and not self._gerais:
            self.painel_problemas.hide()

    # --- assistente: Verible e Verilator -----------------------------------------------------

    def _diagnosticos(self, caminho: Path, locais: list[Local]) -> None:
        self._definir_fonte("verible", {caminho: locais}, so=caminho)
        if caminho == self.atual:
            self._estrutura_pendente.start()

    def _lint_pronto(self, resultado) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        self._gerais = list(resultado.gerais)
        self._definir_fonte("verilator", locais_por_arquivo(projeto.raiz, resultado.locais))
        n = len(resultado.locais) + len(resultado.gerais)
        self.estado_lint.setText("LINT ✓" if not n else f"LINT · {n}")
        resumo = f"{resultado.erros} erro(s), {resultado.avisos} aviso(s)." if n else "nada."
        self.estado_lint.setToolTip(f"O Verilator conferiu o projeto depois de salvar: {resumo}")

    def _estado_lint(self, estado: str, detalhe: str) -> None:
        if estado == "rodando":
            self.estado_lint.setText("LINT …")
        elif estado == "indisponivel":
            self.estado_lint.setText("LINT —")
            self.estado_lint.setToolTip(f"O lint do Verilator não rodou: {detalhe}")

    def _estado_linguagem(self, estado: str, detalhe: str) -> None:
        textos = {
            "iniciando": ("VERIBLE …", "tinta_3",
                          "Subindo o servidor de linguagem (Verible) na imagem de ferramentas."),
            "ativo": ("VERIBLE", "ok", "Servidor de linguagem ativo: erros ao digitar, Formatar, "
                      "F12 vai à definição, Shift+F12 mostra os usos, F2 renomeia."),
            "indisponivel": ("SEM VERIBLE", "aviso",
                             f"Servidor de linguagem indisponível — o editor funciona, mas sem "
                             f"erros ao digitar nem formatação. {detalhe}"),
            "parado": ("", "tinta_3", ""),
        }  # fmt: skip
        texto, token, dica = textos.get(estado, ("", "tinta_3", ""))
        self.estado_ls.setText(texto)
        self.estado_ls.setToolTip(dica)
        self.ponto_ls.definir_token(token)
        self.ponto_ls.setVisible(bool(texto))
        self.ponto_ls.setToolTip(dica)
        self._atualizar_ferramentas()
        if estado == "ativo":
            self._estrutura_pendente.start()
        elif estado == "indisponivel" and self.atual is not None:
            self.estrutura.mensagem("Estrutura indisponível: o servidor de linguagem não subiu.")

    def _atualizar_ferramentas(self) -> None:
        hdl = self.atual is not None and self.assistente.e_hdl(self.atual)
        self.botao_formatar.setEnabled(hdl and self.assistente.ativo)

    def _pedir_estrutura(self) -> None:
        caminho = self.atual
        if caminho is None or not self.assistente.e_hdl(caminho):
            self.estrutura.mensagem("A estrutura aparece para arquivos Verilog e SystemVerilog.")
            return
        if not self.assistente.ativo:
            return

        def chegou(resultado, erro) -> None:
            if caminho == self.atual and not erro:
                self.estrutura.definir([s.como_dict() for s in lg.simbolos(resultado)])

        self.assistente.pedir("textDocument/documentSymbol", lg.documento(caminho), chegou)

    def _textos_para(self, caminhos: list[Path]) -> dict[Path, str]:
        """Texto dos arquivos citados que o Monaco ainda não carregou (dentro do projeto)."""
        projeto = self.sessao.projeto
        textos: dict[Path, str] = {}
        if projeto is None:
            return textos
        for c in dict.fromkeys(caminhos):
            if c in self.abas or c in self._ocultos:
                continue
            try:
                textos[c] = fontes.ler(projeto, c)
            except (fontes.ErroArquivo, OSError):
                continue
            self._textos[c] = textos[c]
            self._ocultos.add(c)
        return textos

    def _pedido_linguagem(self, ident: int, tipo: str, caminho: Path, dados: dict) -> None:
        editor = self.editor
        lugar = lg.em(caminho, dados.get("linha", 1), dados.get("coluna", 1))

        def lugares(r) -> tuple[object, dict]:
            achados = lg.lugares(r)
            textos = self._textos_para([x.caminho for x in achados])
            return [{"caminho": str(x.caminho), **x.faixa.como_dict()} for x in achados], textos

        def renomear(r) -> tuple[object, dict]:
            mudancas = lg.edicoes_de_espaco(r)
            textos = self._textos_para(list(mudancas))
            lista = [{"caminho": str(c), "edicoes": [e.como_dict() for e in es]}
                     for c, es in mudancas.items()]  # fmt: skip
            return lista, textos

        opcoes_formato = {"tabSize": 4, "insertSpaces": True}
        pedidos = {
            "formatar": ("textDocument/formatting",
                         {**lg.documento(caminho), "options": opcoes_formato},
                         lambda r: ([e.como_dict() for e in lg.edicoes(r)], {})),
            "definicao": ("textDocument/definition", lugar, lugares),
            "referencias": ("textDocument/references",
                            {**lugar, "context": {"includeDeclaration": True}}, lugares),
            "destaques": ("textDocument/documentHighlight", lugar,
                          lambda r: ([lg.Faixa.do_lsp(x["range"]).como_dict() for x in r or []],
                                     {})),
            "simbolos": ("textDocument/documentSymbol", lg.documento(caminho),
                         lambda r: ([s.como_dict() for s in lg.simbolos(r)], {})),
            "dica": ("textDocument/hover", lugar, lambda r: (lg.dica(r) or None, {})),
            "renomear": ("textDocument/rename", {**lugar, "newName": dados.get("novo", "")},
                         renomear),
        }  # fmt: skip
        if tipo not in pedidos or editor is None:
            if editor is not None:
                editor.responder(ident, None)
            return
        metodo, params, traduzir = pedidos[tipo]

        def chegou(resultado, erro) -> None:
            if erro or self.editor is not editor:
                editor.responder(ident, None)
                return
            valor, textos = traduzir(resultado)
            editor.responder(ident, valor, textos)

        self.assistente.pedir(metodo, params, chegou)

    # --- arquivo novo ------------------------------------------------------------------------

    def novo_arquivo(self) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        from axillares.gui.dialogos import DialogoNovoArquivo

        dialogo = DialogoNovoArquivo(projeto, self)
        if dialogo.exec() != DialogoNovoArquivo.DialogCode.Accepted:
            return
        self.criar_arquivo(**dialogo.escolhas())

    def criar_arquivo(self, relativo: str, tipo: str = "modulo") -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return

        def criado(novo: fontes.ArquivoNovo) -> None:
            if novo.aviso:
                self.sessao.erro.emit(novo.aviso)
            self.sessao.abrir(projeto.raiz)  # relê o axil.toml e as listas de fontes
            self._abrir_depois = novo.caminho

        self._rodar(lambda: fontes.criar(projeto, relativo, tipo), criado)

    @property
    def tem_alteracoes(self) -> bool:
        return bool(self.sujos)
