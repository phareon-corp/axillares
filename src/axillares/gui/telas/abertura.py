"""Tela 1 — Abertura: situação do ambiente, instalação do toolchain e projetos recentes."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from axillares.ambiente.conteiner import ResultadoInstalacao
from axillares.ambiente.diagnostico import Diagnostico
from axillares.ambiente.executor import Executor
from axillares.ambiente.perfil import Comparacao, Origem, Perfil
from axillares.ambiente.verificacao import FerramentaAvaliada, RelatorioAmbiente, Veredito
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import (
    Eyebrow,
    Metrica,
    NumeroSecao,
    Pilula,
    botao,
    quadro,
    repolir,
    rotulo,
)
from axillares.gui.tema import Espaco, Papel

_ORIGEM = {Origem.CONTEINER: "contêiner", Origem.NATIVA: "nativa"}


def aparencia_do_veredito(f: FerramentaAvaliada) -> tuple[str, str]:
    """(texto, token de cor) da pílula de cada ferramenta."""
    match f.veredito:
        case Veredito.OK:
            return "ok", "ok"
        case Veredito.DIVERGENTE:
            return "divergente", "falha" if f.ferramenta.essencial else "aviso"
        case Veredito.AUSENTE:
            return ("ausente", "falha") if f.ferramenta.essencial else ("opcional", "aviso")
        case Veredito.SEM_IMAGEM:
            return "sem imagem", "aviso"
        case _:
            return "ilegível", "aviso"


class _LinhaFerramenta(QFrame):
    def __init__(self, f: FerramentaAvaliada) -> None:
        super().__init__()
        self.setProperty("tipo", "linha-tabela")
        lay = QGridLayout(self)
        lay.setContentsMargins(Espaco.S, Espaco.M - 4, Espaco.S, Espaco.M - 4)
        lay.setHorizontalSpacing(Espaco.L)
        nome = QVBoxLayout()
        nome.setSpacing(2)
        nome.addWidget(rotulo(f.nome, Papel.CORPO_FORTE))
        nome.addWidget(rotulo(f.ferramenta.descricao, Papel.PEQUENO, "2"))
        lay.addLayout(nome, 0, 0)
        lay.addWidget(rotulo(_ORIGEM[f.ferramenta.origem], Papel.ETIQUETA, "2"), 0, 1)
        lay.addWidget(rotulo(f.encontrada or "—", Papel.MONO), 0, 2)
        esperada = f.ferramenta.versao
        if f.ferramenta.comparacao is Comparacao.MINIMA:
            esperada = f"≥ {esperada}"
        lay.addWidget(rotulo(esperada, Papel.MONO, "2"), 0, 3)
        pilula = Pilula(*aparencia_do_veredito(f))
        lay.addWidget(pilula, 0, 4, Qt.AlignmentFlag.AlignRight)
        for coluna, peso in enumerate((5, 2, 3, 3, 2)):
            lay.setColumnStretch(coluna, peso)
        self.setToolTip(f.diagnostico.o_que if f.diagnostico else "")


def _cabecalho_tabela() -> QWidget:
    w = QWidget()
    lay = QGridLayout(w)
    lay.setContentsMargins(Espaco.S, 0, Espaco.S, Espaco.S)
    lay.setHorizontalSpacing(Espaco.L)
    for coluna, (texto, peso) in enumerate(
        (("ferramenta", 5), ("origem", 2), ("encontrada", 3), ("esperada", 3), ("veredito", 2))
    ):
        r = rotulo(texto, Papel.ROTULO, "3")
        if coluna == 4:
            r.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(r, 0, coluna)
        lay.setColumnStretch(coluna, peso)
    return w


class CartaoDiagnostico(QFrame):
    """O que aconteceu · por que importa · próximo passo. O log fica atrás de um clique."""

    def __init__(self, d: Diagnostico) -> None:
        super().__init__()
        self.setProperty("tipo", "cartao")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.L, Espaco.M + 2, Espaco.L, Espaco.M + 2)
        lay.setSpacing(Espaco.S)
        topo = QHBoxLayout()
        topo.setSpacing(Espaco.S + 2)
        topo.addWidget(Pilula(*(("bloqueante", "falha") if d.bloqueante else ("aviso", "aviso"))))
        topo.addWidget(rotulo(d.codigo, Papel.ROTULO, "3"))
        topo.addStretch(1)
        lay.addLayout(topo)
        o_que = rotulo(d.o_que, Papel.CORPO_FORTE)
        o_que.setWordWrap(True)
        lay.addWidget(o_que)
        por_que = rotulo(d.por_que, Papel.PEQUENO, "2")
        por_que.setWordWrap(True)
        lay.addWidget(por_que)
        passo = QHBoxLayout()
        passo.setSpacing(Espaco.S)
        seta = rotulo("→", Papel.CORPO_FORTE, "acento")
        seta.setAlignment(Qt.AlignmentFlag.AlignTop)
        passo.addWidget(seta)
        texto = rotulo(d.proximo_passo, Papel.CORPO)
        texto.setWordWrap(True)
        texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texto.setCursor(Qt.CursorShape.IBeamCursor)
        passo.addWidget(texto, 1)
        lay.addLayout(passo)
        if d.detalhe:
            self._log = QPlainTextEdit(d.detalhe)
            self._log.setProperty("tipo", "log")
            self._log.setReadOnly(True)
            self._log.setFont(t.fonte(Papel.MONO))
            self._log.setFixedHeight(96)
            self._log.hide()
            alternar = botao("Ver detalhe técnico", "link")
            alternar.setFont(t.fonte(Papel.ETIQUETA))
            alternar.clicked.connect(
                lambda: (
                    self._log.setVisible(not self._log.isVisible()),
                    alternar.setText(
                        "Ocultar detalhe técnico"
                        if self._log.isVisible()
                        else "Ver detalhe técnico"
                    ),
                )
            )
            lay.addWidget(alternar, 0, Qt.AlignmentFlag.AlignLeft)
            lay.addWidget(self._log)


def _limpar(layout: QVBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


class TelaAbertura(QWidget):
    situacao_mudou = Signal(object)

    def __init__(self, perfil: Perfil, fabrica_executor: Callable[[], Executor]) -> None:
        super().__init__()
        self.perfil = perfil
        self._fabrica = fabrica_executor
        self.relatorio: RelatorioAmbiente | None = None
        self._tarefa: tarefas.Tarefa | None = None

        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        externo.addWidget(rolagem, 1)
        externo.addWidget(self._montar_faixa())

        miolo = QWidget()
        rolagem.setWidget(miolo)
        lay = QVBoxLayout(miolo)
        lay.setContentsMargins(Espaco.MARGEM, Espaco.XL + 8, Espaco.MARGEM, Espaco.XXL)
        lay.setSpacing(Espaco.XL)
        lay.addLayout(self._montar_hero())
        lay.addWidget(self._montar_metricas())

        lay.addWidget(NumeroSecao("01", "Ferramentas", f"PERFIL {perfil.identificador}"))
        self._tabela = quadro("tabela")
        self._linhas = QVBoxLayout(self._tabela)
        self._linhas.setContentsMargins(0, 0, 0, 0)
        self._linhas.setSpacing(0)
        bloco = QVBoxLayout()
        bloco.setSpacing(0)
        bloco.addWidget(_cabecalho_tabela())
        bloco.addWidget(self._tabela)
        lay.addLayout(bloco)

        self._secao_diag = NumeroSecao("02", "O que fazer")
        lay.addWidget(self._secao_diag)
        self._diags = QVBoxLayout()
        self._diags.setSpacing(Espaco.M - 4)
        lay.addLayout(self._diags)

        lay.addWidget(NumeroSecao("03", "Projetos recentes"))
        vazio = quadro("cartao")
        vl = QVBoxLayout(vazio)
        vl.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.L)
        vl.setSpacing(6)
        vl.addWidget(rotulo("Nenhum projeto ainda.", Papel.CORPO_FORTE))
        aviso = rotulo(
            "Criar, abrir e executar projetos chega no próximo módulo (projeto, motor e caderno "
            "de execuções). O ambiente acima já é o mesmo que eles vão usar.",
            Papel.PEQUENO,
            "2",
        )
        aviso.setWordWrap(True)
        vl.addWidget(aviso)
        lay.addWidget(vazio)
        lay.addStretch(1)

        rodape = rotulo(
            "SOFTWARE LIVRE · APACHE-2.0 · FERRAMENTAS ABERTAS CHAMADAS COMO PROCESSOS EXTERNOS",
            Papel.ROTULO,
            "3",
        )
        lay.addWidget(rodape)

    # --- montagem -------------------------------------------------------------------------

    def _montar_hero(self) -> QVBoxLayout:
        hero = QVBoxLayout()
        hero.setSpacing(Espaco.M + 2)
        hero.addWidget(Eyebrow(f"Ambiente · {self.perfil.nome} {self.perfil.versao}"))
        titulo = rotulo(
            f"Do Verilog ao {t.serifa('silício,', tamanho_px=54)}<br>sem montar o ambiente à mão.",
            Papel.HERO,
            rico=True,
        )
        hero.addWidget(titulo)
        lead = rotulo(
            "O Axillares baixa uma imagem fixada com as ferramentas abertas, confere a versão de "
            "cada uma e diz, em português, o que fazer quando algo falta.",
            Papel.LEAD,
            "2",
        )
        lead.setWordWrap(True)
        lead.setMaximumWidth(600)
        hero.addWidget(lead)
        hero.addSpacing(Espaco.S)

        situacao = QHBoxLayout()
        situacao.setSpacing(Espaco.M)
        self._pilula = Pilula("verificando", "tinta_3")
        situacao.addWidget(self._pilula, 0, Qt.AlignmentFlag.AlignVCenter)
        self._frase = rotulo("Consultando o ambiente…", Papel.TITULO)
        situacao.addWidget(self._frase, 0, Qt.AlignmentFlag.AlignVCenter)
        situacao.addStretch(1)
        self.botao_instalar = botao("Instalar ferramentas  ↓", "primario")
        self.botao_instalar.clicked.connect(self.instalar)
        self.botao_instalar.hide()
        self.botao_verificar = botao("Verificar de novo", "fantasma")
        self.botao_verificar.clicked.connect(self.verificar)
        situacao.addWidget(self.botao_instalar)
        situacao.addWidget(self.botao_verificar)
        hero.addLayout(situacao)
        return hero

    def _montar_metricas(self) -> QFrame:
        grade = quadro("grade")
        lay = QHBoxLayout(grade)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.m_ferramentas = Metrica("Ferramentas conferidas")
        self.m_essenciais = Metrica("Essenciais")
        self.m_imagem = Metrica("Imagem")
        self.m_conteiner = Metrica("Contêiner")
        for m in (self.m_ferramentas, self.m_essenciais, self.m_imagem, self.m_conteiner):
            lay.addWidget(m, 1)
        tag = self.perfil.imagem.tag
        self.m_imagem.definir(
            f"{self.perfil.imagem.tamanho_gb:.1f}".replace(".", ","),
            "GB",
            f"{self.perfil.imagem.repositorio.rsplit('/', 1)[-1]} {tag} · fixada por digest",
        )
        return grade

    def _montar_faixa(self) -> QFrame:
        self._faixa = quadro("faixa-progresso")
        lay = QVBoxLayout(self._faixa)
        lay.setContentsMargins(Espaco.MARGEM, Espaco.M, Espaco.MARGEM, Espaco.M)
        lay.setSpacing(Espaco.S)
        topo = QHBoxLayout()
        self._faixa_titulo = rotulo("Baixando a imagem de ferramentas", Papel.CORPO_FORTE)
        self._faixa_contagem = rotulo("", Papel.ETIQUETA, "2")
        topo.addWidget(self._faixa_titulo)
        topo.addStretch(1)
        topo.addWidget(self._faixa_contagem)
        lay.addLayout(topo)
        self._barra = QProgressBar()
        self._barra.setTextVisible(False)
        lay.addWidget(self._barra)
        self._faixa_linha = rotulo("", Papel.MONO, "3")
        self._faixa_linha.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self._faixa_linha)
        self._faixa.hide()
        return self._faixa

    # --- ações ----------------------------------------------------------------------------

    def verificar(self) -> None:
        if self._tarefa and self._tarefa.rodando:
            return
        self._pilula.definir("verificando", "tinta_3")
        self._frase.setText("Consultando o ambiente…")
        self.botao_verificar.setEnabled(False)
        self._tarefa = tarefas.avaliar(self.perfil, self._fabrica(), self)
        self._tarefa.concluido.connect(self.mostrar)
        self._tarefa.falhou.connect(self._falha_interna)
        self._tarefa.iniciar()

    def instalar(self) -> None:
        if self._tarefa and self._tarefa.rodando:
            return
        self.botao_instalar.setEnabled(False)
        self.botao_verificar.setEnabled(False)
        self._barra.setRange(0, self.perfil.imagem.camadas)
        self._barra.setValue(0)
        self._faixa_titulo.setText(
            f"Baixando {self.perfil.imagem.repositorio}:{self.perfil.imagem.tag}"
        )
        self._faixa.show()
        self._tarefa = tarefas.instalar(self.perfil, self._fabrica(), self)
        self._tarefa.progresso.connect(self._ao_progredir)
        self._tarefa.concluido.connect(self._instalacao_concluida)
        self._tarefa.falhou.connect(self._falha_interna)
        self._tarefa.iniciar()

    def _ao_progredir(self, feitas: int, total: int, linha: str) -> None:
        self._barra.setMaximum(total)
        self._barra.setValue(feitas)
        self._faixa_contagem.setText(f"camadas {feitas}/{total}")
        self._faixa_linha.setText(linha[:140])

    def _instalacao_concluida(self, resultado: ResultadoInstalacao) -> None:
        self.botao_instalar.setEnabled(True)
        if resultado.ok:
            self._faixa.hide()
            self.verificar()
            return
        self._faixa_titulo.setText("O download não terminou")
        self._faixa_linha.setText("Veja abaixo o que aconteceu e o próximo passo.")
        self.botao_verificar.setEnabled(True)
        if resultado.diagnostico:
            _limpar(self._diags)
            self._secao_diag.show()
            self._diags.addWidget(CartaoDiagnostico(resultado.diagnostico))

    def _falha_interna(self, mensagem: str) -> None:
        self.botao_verificar.setEnabled(True)
        self.botao_instalar.setEnabled(True)
        self._pilula.definir("erro interno", "falha")
        self._frase.setText("O Axillares falhou ao consultar o ambiente.")
        _limpar(self._diags)
        self._diags.addWidget(
            CartaoDiagnostico(
                Diagnostico(
                    codigo="erro-interno",
                    o_que="Um erro inesperado interrompeu a verificação.",
                    por_que="Isto é um defeito do Axillares, não do seu ambiente.",
                    proximo_passo="Rode “axil ambiente situacao” no terminal e relate o problema "
                    "com a saída.",
                    detalhe=mensagem,
                )
            )
        )

    # --- apresentação ---------------------------------------------------------------------

    def mostrar(self, relatorio: RelatorioAmbiente) -> None:
        self.relatorio = relatorio
        self.botao_verificar.setEnabled(True)
        conta = relatorio.contagem()
        total = len(relatorio.ferramentas)
        essenciais = [f for f in relatorio.ferramentas if f.ferramenta.essencial]
        ess_ok = sum(1 for f in essenciais if f.veredito is Veredito.OK)

        if relatorio.aprovado:
            self._pilula.definir("pronto", "ok")
            self._frase.setText("Pronto para o fluxo.")
        elif relatorio.programa is None:
            self._pilula.definir("sem contêiner", "falha")
            self._frase.setText("Falta um programa de contêiner.")
        elif any(d.codigo == "imagem-ausente" for d in relatorio.diagnosticos):
            self._pilula.definir("falta a imagem", "aviso")
            self._frase.setText("Falta baixar as ferramentas.")
        else:
            self._pilula.definir("incompleto", "falha")
            self._frase.setText("O ambiente precisa de atenção.")
        precisa_instalar = relatorio.programa is not None and any(
            d.codigo in {"imagem-ausente", "digest-divergente"} for d in relatorio.diagnosticos
        )
        self.botao_instalar.setVisible(precisa_instalar)

        self.m_ferramentas.definir(
            str(conta[Veredito.OK]), f"/{total}", "versões lidas e comparadas com o perfil"
        )
        self.m_essenciais.definir(
            str(ess_ok), f"/{len(essenciais)}", "as que o fluxo precisa para rodar"
        )
        if relatorio.programa:
            extra = "sem root, sem serviço" if relatorio.programa.nome == "podman" else "no PATH"
            self.m_conteiner.definir(
                relatorio.programa.nome, "", f"versão {relatorio.programa.versao} · {extra}"
            )
        else:
            self.m_conteiner.definir("—", "", "nem podman nem docker")

        _limpar(self._linhas)
        for f in relatorio.ferramentas:
            self._linhas.addWidget(_LinhaFerramenta(f))

        _limpar(self._diags)
        diagnosticos = relatorio.todos_os_diagnosticos
        self._secao_diag.apoio.setText(
            f"{len(diagnosticos)} {'ITEM' if len(diagnosticos) == 1 else 'ITENS'}"
        )
        if not diagnosticos:
            ok = rotulo("Nada a fazer: tudo o que o perfil promete está aqui.", Papel.CORPO, "2")
            self._diags.addWidget(ok)
        for d in diagnosticos:
            self._diags.addWidget(CartaoDiagnostico(d))
        repolir(self)
        self.situacao_mudou.emit(relatorio)

    def encerrar(self) -> None:
        if self._tarefa and self._tarefa.rodando:
            self._tarefa.esperar(5000)


__all__ = ["CartaoDiagnostico", "TelaAbertura", "aparencia_do_veredito"]
