"""Tela 3 — Editor: arquivos do projeto, abas, Monaco, execução e problemas no mesmo lugar."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, Signal
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

from axillares.core import fontes
from axillares.core import formato as fmt
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, Local, Situacao
from axillares.core.projeto import Projeto
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import Pilula, Ponto, Tabela, botao, quadro, rotulo, tom_da_situacao
from axillares.gui.sessao import Sessao
from axillares.gui.tema import Espaco, Papel

PAPEL_CAMINHO = Qt.ItemDataRole.UserRole
NOMES_LINGUAGEM = {
    "systemverilog": "SystemVerilog",
    "tcl": "Tcl / SDC",
    "python": "Python",
    "markdown": "Markdown",
    "ini": "TOML",
    "shell": "Shell",
    "plaintext": "Texto",
}


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
    def __init__(self, sessao: Sessao, fabrica_editor: Callable[[], QWidget] | None = None) -> None:
        super().__init__()
        self.sessao = sessao
        self._fabrica_editor = fabrica_editor
        self.editor = None  # criado na primeira vez que a tela aparece
        self.abas: dict[Path, Aba] = {}
        self.sujos: set[Path] = set()
        self.atual: Path | None = None
        self._textos: dict[Path, str] = {}
        self._pendentes_ao_abrir: list[tuple[Path, int, int]] = []
        self._problemas: dict[Path, list[Local]] = {}
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
        cabeca.addWidget(rotulo("Arquivos", Papel.ROTULO, "3"))
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
        lateral.setMinimumWidth(200)
        divisor.addWidget(lateral)

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
        self.botao_salvar = botao("Salvar", "compacto")
        self.botao_salvar.setToolTip("Ctrl+S")
        self.botao_salvar.clicked.connect(lambda: self.editor and self.editor.salvar())
        self.botao_sintese = botao("Síntese  ▸", "compacto")
        self.botao_sintese.setToolTip("Ctrl+Enter — salva tudo e executa a síntese")
        self.botao_sintese.clicked.connect(lambda: self.sessao.executar(Etapa.SINTESE))
        self.botao_gds = botao("GDS  ▸", "compacto-primario")
        self.botao_gds.setToolTip("Ctrl+Shift+Enter — salva tudo e executa o fluxo até o GDS")
        self.botao_gds.clicked.connect(lambda: self.sessao.executar(Etapa.GDS))
        for w in (self.botao_salvar, self.botao_sintese, self.botao_gds):
            b.addSpacing(6)
            b.addWidget(w)
        col.addWidget(barra)

        self.caminho = rotulo("", Papel.ETIQUETA, "3")
        self.caminho.setContentsMargins(Espaco.M + 2, 6, Espaco.M, 6)
        col.addWidget(self.caminho)

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
            [("", 1, "e"), ("arquivo", 4, "e"), ("linha", 1, "d"), ("mensagem", 12, "e")],
            [Papel.CORPO, Papel.MONO, Papel.MONO, Papel.MONO],
        )
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
        e.addStretch(1)
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
        divisor.setSizes([250, 1000])

        self._inicio = 0.0
        self._ultimo: RegistroExecucao | None = None
        self._passo = ""
        self._relogio = QTimer(self)
        self._relogio.setInterval(200)
        self._relogio.timeout.connect(self._tique)
        self.ver_execucao.clicked.connect(
            lambda: self._ultimo and self.sessao.pedir_tela.emit("execucao", self._ultimo.id)
        )

        sessao.projeto_mudou.connect(self._projeto_mudou)
        sessao.execucao_iniciada.connect(self._execucao_iniciada)
        sessao.execucao_linha.connect(self._execucao_linha)
        sessao.execucao_concluida.connect(self._execucao_concluida)
        sessao.antes_de_executar = self._salvar_e_seguir
        self._mostrar_vazio()

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
        self._lugar_editor.addWidget(self.editor)

    def _rodar(self, funcao, ao_concluir) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(self.sessao.erro)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    # --- projeto e árvore ---------------------------------------------------------------------

    def _projeto_mudou(self, projeto: Projeto | None) -> None:
        for caminho in list(self.abas):
            self._fechar(caminho, forcar=True)
        self._problemas.clear()
        self.painel_problemas.hide()
        self.arvore.clear()
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
        projeto = self.sessao.projeto
        for g in grupos:
            topo = QTreeWidgetItem([g.nome.upper()])
            topo.setFont(0, t.fonte(Papel.ROTULO))
            topo.setFlags(Qt.ItemFlag.ItemIsEnabled)
            topo.setForeground(0, t.paleta().qcolor("tinta_3"))
            self.arvore.addTopLevelItem(topo)
            for arquivo in g.arquivos:
                rel = projeto.relativo(arquivo) if projeto else arquivo.name
                item = QTreeWidgetItem([arquivo.name])
                item.setToolTip(0, rel)
                item.setData(0, PAPEL_CAMINHO, str(arquivo))
                item.setFont(0, t.fonte(Papel.PEQUENO))
                topo.addChild(item)
            topo.setExpanded(True)
        self._marcar_arvore()

    def _marcar_arvore(self) -> None:
        for i in range(self.arvore.topLevelItemCount()):
            topo = self.arvore.topLevelItem(i)
            for j in range(topo.childCount()):
                item = topo.child(j)
                caminho = Path(item.data(0, PAPEL_CAMINHO))
                nome = caminho.name + ("  ●" if caminho in self.sujos else "")
                if self._problemas.get(caminho):
                    nome += f"  ✕ {len(self._problemas[caminho])}"
                item.setText(0, nome)
                cor = (
                    "falha"
                    if self._problemas.get(caminho)
                    else ("tinta" if caminho == self.atual else "tinta_2")
                )
                item.setForeground(0, t.paleta().qcolor(cor))

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

    def _aberto(self, par: tuple[Path, str]) -> None:
        caminho, texto = par
        if caminho not in self.abas:
            aba = Aba(caminho, caminho.name)
            aba.clicada.connect(self._ativar)
            aba.fechar.connect(self._fechar)
            self._lay_abas.insertWidget(self._lay_abas.count() - 1, aba)
            self.abas[caminho] = aba
            self._textos[caminho] = texto
            self.editor.abrir(caminho, texto)
            if str(caminho) not in self._vigia.files():
                self._vigia.addPath(str(caminho))
            if self._problemas.get(caminho):
                self.editor.problemas(caminho, self._problemas[caminho])
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
        self.caminho.setText(f"{projeto.nome if projeto else ''} / {rel}".upper())
        self._atualizar_abas()

    def _atualizar_abas(self) -> None:
        for caminho, aba in self.abas.items():
            aba.definir(caminho == self.atual, caminho in self.sujos)
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
        self.caminho.setText("")
        self.posicao.setText("")
        self.linguagem.setText("")
        self.situacao_arquivo.setText("")

    # --- gravar -------------------------------------------------------------------------------

    def _sujo_mudou(self, caminho: Path, sujo: bool) -> None:
        if sujo:
            self.sujos.add(caminho)
        else:
            self.sujos.discard(caminho)
        self._atualizar_abas()

    def _cursor_mudou(self, linha: int, coluna: int, linguagem: str) -> None:
        self.posicao.setText(f"LN {linha}, COL {coluna}")
        self.linguagem.setText(NOMES_LINGUAGEM.get(linguagem, linguagem).upper())

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
        self.botao_sintese.setEnabled(False)
        self.botao_gds.setEnabled(False)
        self._relogio.start()
        self._tique()

    def _execucao_linha(self, _linha: str, passo: str | None) -> None:
        if passo:
            self._passo = passo

    def _tique(self) -> None:
        decorrido = fmt.duracao(time.monotonic() - self._inicio)
        self.estado_execucao.setText(f"{self._passo.upper()}   {decorrido}")

    def _execucao_concluida(self, r: RegistroExecucao) -> None:
        self._relogio.stop()
        self._ultimo = r
        self.botao_sintese.setEnabled(True)
        self.botao_gds.setEnabled(True)
        texto, token = tom_da_situacao(r.situacao)
        self.ponto_execucao.definir_token(token)
        self.pilula.definir(texto, token)
        self.pilula.show()
        self.ver_execucao.show()
        resumo = f"#{r.numero} {r.etapa.value} · {fmt.duracao(r.duracao_s)}"
        m = r.metrica("fmax_mhz")
        if m and r.situacao is Situacao.SUCESSO:
            resumo += f" · Fmax {fmt.numero(m.valor, 1)} MHz"
        self.estado_execucao.setText(resumo.upper())
        locais = r.falha.locais if r.falha else []
        self.mostrar_problemas(locais)

    def mostrar_problemas(self, locais: list[Local]) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        antigos = set(self._problemas)
        self._problemas = {}
        for local in locais:
            self._problemas.setdefault((projeto.raiz / local.arquivo).resolve(), []).append(local)
        if self.editor is not None:
            for caminho in antigos | set(self._problemas):
                if caminho in self.abas:
                    self.editor.problemas(caminho, self._problemas.get(caminho, []))
        self.tabela_problemas.limpar()
        if not locais:
            self.painel_problemas.hide()
            self._marcar_arvore()
            return
        erros = sum(1 for x in locais if x.gravidade == "erro")
        self.titulo_problemas.setText(
            f"PROBLEMAS · {erros} ERRO(S) · {len(locais) - erros} AVISO(S)"
        )
        for local in locais:
            caminho = (projeto.raiz / local.arquivo).resolve()
            marca = rotulo("✕" if local.gravidade == "erro" else "!", Papel.CORPO_FORTE,
                           "falha" if local.gravidade == "erro" else "aviso")  # fmt: skip
            self.tabela_problemas.adicionar(
                [marca, local.arquivo, str(local.linha), local.mensagem],
                ao_clicar=lambda c=caminho, x=local: self.abrir(c, x.linha, x.coluna),
                tons=[None, "2", "2", None],
            )
        self.painel_problemas.show()
        self._marcar_arvore()
        primeiro = locais[0]
        self.abrir((projeto.raiz / primeiro.arquivo).resolve(), primeiro.linha, primeiro.coluna)

    @property
    def tem_alteracoes(self) -> bool:
        return bool(self.sujos)
