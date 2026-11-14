"""Tela 2 — Projeto: resumo do axil.toml, uma ação por etapa e a execução ao vivo."""

from __future__ import annotations

import html
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares.core import explicacoes as ex
from axillares.core import formato as fmt
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, Situacao, TipoArtefato
from axillares.core.projeto import Projeto
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import (
    GradeResponsiva,
    LinhaResponsiva,
    Metrica,
    NumeroSecao,
    Pilula,
    Ponto,
    botao,
    cabecalho_tela,
    layout_de_tela,
    rotulo,
    tela_rolavel,
    tom_da_situacao,
)
from axillares.gui.dialogos import DialogoNovoProjeto
from axillares.gui.sessao import Sessao
from axillares.gui.telas.fluxo import FluxoExplicado
from axillares.gui.tema import Espaco, Papel

TITULOS_ETAPA = {Etapa.SINTESE: "Síntese", Etapa.GDS: "Do RTL ao GDS"}
LIMITE_LOG = 4000


# --- diálogo de projeto novo ------------------------------------------------------------------


# --- execução ao vivo -------------------------------------------------------------------------


class PainelExecucao(QFrame):
    """Etapa corrente, linha do tempo dos passos do motor, tempo, log e cancelar."""

    def __init__(self, tela: TelaProjeto) -> None:
        super().__init__()
        self.tela = tela
        self.setProperty("tipo", "painel-execucao")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.L)
        lay.setSpacing(Espaco.M)

        topo = QHBoxLayout()
        topo.setSpacing(Espaco.M)
        self.ponto = Ponto(8, "acento", pulsar=True)
        topo.addWidget(self.ponto, 0, Qt.AlignmentFlag.AlignVCenter)
        coluna = QVBoxLayout()
        coluna.setSpacing(2)
        self.rotulo_etapa = rotulo("", Papel.ROTULO, "3")
        self.passo = rotulo("preparando…", Papel.TITULO)
        coluna.addWidget(self.rotulo_etapa)
        coluna.addWidget(self.passo)
        topo.addLayout(coluna, 1)
        self.relogio = rotulo("0,0 s", Papel.MONO, "2")
        topo.addWidget(self.relogio, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pilula = Pilula("executando", "acento")
        self.pilula.hide()
        topo.addWidget(self.pilula, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cancelar = botao("Cancelar", "fantasma")
        topo.addWidget(self.cancelar, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(topo)

        self.explicacao = rotulo("", Papel.CORPO, "2")
        self.explicacao.setWordWrap(True)
        self.explicacao.setMaximumWidth(760)
        lay.addWidget(self.explicacao)

        self.trilha = rotulo("", Papel.ETIQUETA, "2", rico=True)
        self.trilha.setWordWrap(True)
        lay.addWidget(self.trilha)

        self.resumo = rotulo("", Papel.CORPO, rico=True)
        self.resumo.setWordWrap(True)
        self.resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.resumo.hide()
        lay.addWidget(self.resumo)

        acoes = QHBoxLayout()
        acoes.setSpacing(Espaco.S + 2)
        self.ver_detalhe = botao("Ver detalhe  →", "primario")
        self.alternar_log = botao("Mostrar log", "link")
        self.alternar_log.setFont(t.fonte(Papel.ETIQUETA))
        acoes.addWidget(self.ver_detalhe)
        acoes.addWidget(self.alternar_log)
        acoes.addStretch(1)
        self.ver_detalhe.hide()
        lay.addLayout(acoes)

        self.log = QPlainTextEdit()
        self.log.setProperty("tipo", "log")
        self.log.setReadOnly(True)
        self.log.setFont(t.fonte(Papel.MONO))
        self.log.setMaximumBlockCount(LIMITE_LOG)
        self.log.setFixedHeight(240)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.hide()
        lay.addWidget(self.log)
        self.alternar_log.clicked.connect(self._alternar_log)

        self._passos: list[str] = []
        self._inicio = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tique)

    def _alternar_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())
        self.alternar_log.setText("Ocultar log" if self.log.isVisible() else "Mostrar log")

    def comecar(self, etapa: Etapa, motor: str) -> None:
        self.rotulo_etapa.setText(f"{etapa.value} · {motor}")
        self.passo.setText("preparando…")
        self.relogio.setText("0,0 s")
        self.log.clear()
        self.explicacao.setText("Preparando o contêiner com as ferramentas…")
        self.explicacao.show()
        self._passos = []
        self.trilha.setText("")
        self.resumo.hide()
        self.ver_detalhe.hide()
        self.pilula.hide()
        self.cancelar.show()
        self.cancelar.setEnabled(True)
        self.ponto.definir_token("acento")
        self._inicio = time.monotonic()
        self._timer.start()
        self.show()

    def _tique(self) -> None:
        self.relogio.setText(fmt.duracao(time.monotonic() - self._inicio))

    def receber(self, linha: str, passo: str | None) -> None:
        self.log.appendPlainText(linha)
        if passo:
            self._passos.append(passo.split(" · ")[0])
            self.passo.setText(passo)
            self._desenhar_trilha()

    def _desenhar_trilha(self, final: bool = False) -> None:
        pal = t.paleta()
        unicos: list[str] = []
        for p in self._passos:
            if not unicos or unicos[-1] != p:
                unicos.append(p)
        partes = []
        for i, p in enumerate(unicos):
            atual = i == len(unicos) - 1 and not final
            cor = pal.acento if atual else pal.tinta_2
            marca = "●" if atual else "✓"
            partes.append(f'<span style="color:{cor}">{marca}&nbsp;{p}</span>')
        self.trilha.setText("&nbsp;&nbsp;&nbsp;".join(partes))

    def terminar(self, r: RegistroExecucao) -> None:
        self._timer.stop()
        self.cancelar.hide()
        texto, token = tom_da_situacao(r.situacao)
        self.pilula.definir(texto, token)
        self.pilula.show()
        self.ponto.definir_token(token)
        self.relogio.setText(fmt.duracao(r.duracao_s))
        self._desenhar_trilha(final=r.situacao is Situacao.SUCESSO)
        pal = t.paleta()
        if r.situacao is Situacao.SUCESSO:
            self.passo.setText(f"Execução #{r.numero} concluída.")
            partes = []
            for chave, (rot, casas) in fmt.METRICAS_PRINCIPAIS.items():
                m = r.metrica(chave)
                if m:
                    partes.append(
                        f"<span style='color:{pal.tinta_2}'>{rot}</span>&nbsp;"
                        f"<b>{fmt.numero(m.valor, casas)}</b>&nbsp;"
                        f"<span style='color:{pal.tinta_2}'>{m.unidade}</span>"
                    )
            self.resumo.setText("&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;".join(partes))
        else:
            falha = r.falha
            self.passo.setText(falha.resumo if falha else "A execução não terminou.")
            linhas = []
            if falha and falha.mensagens:
                msgs = "<br>".join(_escapar(m) for m in falha.mensagens[:6])
                linhas.append(
                    f"<span style='font-family:\"Geist Mono\"; color:{pal.tinta_2}'>{msgs}</span>"
                )
            if falha and falha.proximo_passo:
                linhas.append(
                    f"<span style='color:{pal.acento}'>→</span>&nbsp;"
                    f"{_escapar(falha.proximo_passo)}"
                )
            self.resumo.setText("<br><br>".join(linhas))
        self.resumo.show()
        self.ver_detalhe.show()


def _escapar(texto: str) -> str:
    """Texto do motor dentro de rich text: escapa HTML e preserva a indentação (o ^ do erro)."""
    escapado = html.escape(texto)
    recuo = len(escapado) - len(escapado.lstrip(" "))
    return "&nbsp;" * recuo + escapado.lstrip(" ")


# --- tela -------------------------------------------------------------------------------------


class CartaoEtapa(QFrame):
    def __init__(self, numero: str, etapa: Etapa, tela: TelaProjeto) -> None:
        super().__init__()
        self.etapa = etapa
        self.setProperty("tipo", "cartao-etapa")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.L)
        lay.setSpacing(Espaco.S + 2)
        lay.addWidget(rotulo(f"{numero} / {etapa.value}", Papel.NUMERO_SECAO, "acento"))
        lay.addWidget(rotulo(TITULOS_ETAPA[etapa], Papel.TITULO))
        resumo = ex.etapa(etapa)
        desc = rotulo(resumo.resumo, Papel.PEQUENO, "2")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        n = len(resumo.passos)
        lay.addWidget(rotulo(f"{n} passos — veja abaixo como funciona cada um", Papel.ROTULO, "3"))
        self.ultima = rotulo("Ainda não executada.", Papel.MONO, "3")
        self.ultima.setWordWrap(True)
        lay.addWidget(self.ultima)
        lay.addStretch(1)
        self.botao = botao("Executar  →", "fantasma")
        self.botao.clicked.connect(lambda: tela.executar(etapa))
        lay.addWidget(self.botao, 0, Qt.AlignmentFlag.AlignLeft)


class TelaProjeto(QWidget):
    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self._ultimo: RegistroExecucao | None = None

        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        self.pilha = QStackedWidget()
        externo.addWidget(self.pilha)
        self.pilha.addWidget(tela_rolavel(self._montar_vazio()))
        self.pilha.addWidget(tela_rolavel(self._montar_projeto()))
        sessao.projeto_mudou.connect(self.mostrar)
        sessao.execucoes_mudaram.connect(self._atualizar_ultimas)
        sessao.execucao_iniciada.connect(self._iniciada)
        sessao.execucao_linha.connect(self._linha)
        sessao.execucao_concluida.connect(self._concluida)

    # --- montagem -----------------------------------------------------------------------------

    def _montar_vazio(self) -> QWidget:
        w = QWidget()
        lay = layout_de_tela(w)
        cab, _ = cabecalho_tela(
            "Projeto",
            f"Nenhum projeto {t.serifa('aberto', tamanho_px=54)} ainda.",
            "Crie um a partir do exemplo — um contador de 8 bits pronto para ir do Verilog ao "
            "GDS — ou abra uma pasta que já tenha um axil.toml.",
        )
        lay.addLayout(cab)
        acoes = QHBoxLayout()
        acoes.setSpacing(Espaco.S + 2)
        novo = botao("Novo projeto  +", "primario")
        novo.clicked.connect(self.novo_projeto)
        abrir = botao("Abrir pasta…", "fantasma")
        abrir.clicked.connect(self.abrir_pasta)
        acoes.addWidget(novo)
        acoes.addWidget(abrir)
        acoes.addStretch(1)
        lay.addLayout(acoes)
        lay.addStretch(1)
        return w

    def _montar_projeto(self) -> QWidget:
        w = QWidget()
        lay = layout_de_tela(w)
        linha_topo = LinhaResponsiva(limiar=820)
        topo = linha_topo.caixa
        cab, self.titulo = cabecalho_tela("Projeto", "")
        self.titulo.setWordWrap(True)
        self.eyebrow = cab.itemAt(0).widget()
        self.descricao = rotulo("", Papel.LEAD, "2")
        self.descricao.setWordWrap(True)
        self.descricao.setMaximumWidth(620)
        cab.addWidget(self.descricao)
        topo.addLayout(cab, 1)
        lateral = QVBoxLayout()
        lateral.addStretch(1)
        acoes = QHBoxLayout()
        acoes.setSpacing(Espaco.S + 2)
        pasta = botao("Abrir pasta", "fantasma")
        pasta.clicked.connect(self._abrir_no_gerenciador)
        trocar = botao("Abrir outro…", "fantasma")
        trocar.clicked.connect(self.abrir_pasta)
        acoes.addWidget(pasta)
        acoes.addWidget(trocar)
        acoes.addStretch(1)
        lateral.addLayout(acoes)
        topo.addLayout(lateral)
        lay.addWidget(linha_topo)

        grade = GradeResponsiva(min_coluna=200)
        self.m_topo = Metrica("Módulo de topo")
        self.m_pdk = Metrica("PDK")
        self.m_relogio = Metrica("Relógio alvo")
        self.m_fontes = Metrica("Fontes RTL")
        for m in (self.m_topo, self.m_pdk, self.m_relogio, self.m_fontes):
            grade.adicionar(m)
        lay.addWidget(grade)

        lay.addWidget(NumeroSecao("01", "Etapas", "UMA EXECUÇÃO POR CLIQUE · TUDO VAI PARA runs/"))
        caixa = GradeResponsiva(min_coluna=340, max_colunas=2)
        self.cartoes = {
            Etapa.SINTESE: CartaoEtapa("01", Etapa.SINTESE, self),
            Etapa.GDS: CartaoEtapa("02", Etapa.GDS, self),
        }
        for c in self.cartoes.values():
            caixa.adicionar(c)
        lay.addWidget(caixa)

        lay.addWidget(NumeroSecao("02", "Como funciona", "CLIQUE NUM PASSO PARA DETALHES"))
        intro = rotulo(
            "Um chip sai do seu Verilog em passos. Cada passo é uma ferramenta aberta, chamada "
            "pelo "
            "SiliconCompiler dentro da imagem de ferramentas. Durante uma execução, o passo atual "
            "acende aqui.",
            Papel.CORPO,
            "2",
        )
        intro.setWordWrap(True)
        intro.setMaximumWidth(760)
        lay.addWidget(intro)
        self.fluxo = FluxoExplicado()
        lay.addWidget(self.fluxo)

        self.secao_execucao = NumeroSecao("03", "Execução")
        lay.addWidget(self.secao_execucao)
        self.painel = PainelExecucao(self)
        self.painel.cancelar.clicked.connect(self.cancelar)
        self.painel.ver_detalhe.clicked.connect(
            lambda: self._ultimo and self.sessao.pedir_tela.emit("execucao", self._ultimo.id)
        )
        lay.addWidget(self.painel)
        self.secao_execucao.hide()
        self.painel.hide()
        lay.addStretch(1)
        return w

    # --- ações --------------------------------------------------------------------------------

    def novo_projeto(self) -> None:
        dialogo = DialogoNovoProjeto(self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            # o espaço de trabalho abre o projeto novo numa aba própria
            self.sessao.pedir_tela.emit("criar-projeto", dialogo.escolhas())

    def abrir_pasta(self) -> None:
        inicio = str(self.sessao.projeto.raiz) if self.sessao.projeto else str(Path.home())
        pasta = QFileDialog.getExistingDirectory(
            self, "Abrir projeto (pasta com axil.toml)", inicio
        )
        if pasta:
            self.sessao.pedir_tela.emit("abrir-projeto", Path(pasta))

    def _abrir_no_gerenciador(self) -> None:
        if self.sessao.projeto:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.sessao.projeto.raiz)))

    def executar(self, etapa: Etapa) -> None:
        self.sessao.executar(etapa)

    def _iniciada(self, etapa: Etapa, nome_motor: str) -> None:
        for c in self.cartoes.values():
            c.botao.setEnabled(False)
        self.secao_execucao.show()
        self.fluxo.comecar(etapa)
        self.painel.comecar(etapa, nome_motor)

    def _linha(self, linha: str, passo: str | None) -> None:
        self.painel.receber(linha, passo)
        if passo:
            explicado = self.fluxo.avancar(passo.split(" · ")[-1])
            if explicado is not None:
                self.painel.explicacao.setText(f"Agora — {explicado.titulo}: {explicado.o_que}")

    def cancelar(self) -> None:
        if self.sessao.executando:
            self.sessao.cancelar()
            self.painel.cancelar.setEnabled(False)
            self.painel.passo.setText("Interrompendo…")

    def _concluida(self, registro: RegistroExecucao) -> None:
        self._ultimo = registro
        for c in self.cartoes.values():
            c.botao.setEnabled(True)
        self.painel.terminar(registro)
        self.fluxo.terminar(registro.situacao is Situacao.SUCESSO)
        if registro.situacao is Situacao.SUCESSO:
            self.painel.explicacao.setText(
                "Pronto. Veja as métricas abaixo; em Execuções cada uma é explicada, e em Layout "
                "você vê o chip desenhado."
                if registro.etapa is Etapa.GDS
                else "Pronto. A netlist está em Execuções; a etapa GDS continua daqui até o chip."
            )
        else:
            self.painel.explicacao.hide()

    def mostrar_fluxo(self) -> None:
        """Rola até a seção "Como funciona"."""
        rolagem = self.pilha.widget(1)
        QTimer.singleShot(50, lambda: rolagem.ensureWidgetVisible(self.fluxo, 0, 120))

    @property
    def executando(self) -> bool:
        return self.sessao.executando

    # --- apresentação -------------------------------------------------------------------------

    def mostrar(self, projeto: Projeto | None) -> None:
        if projeto is None:
            self.pilha.setCurrentIndex(0)
            return
        self.pilha.setCurrentIndex(1)
        p = projeto
        self.eyebrow.texto.setText(
            f"PROJETO · {p.asic.pdk.value} · {p.asic.biblioteca_efetiva}".upper()
        )
        self.titulo.setText(p.nome)
        self.descricao.setText(p.projeto.descricao or str(p.raiz))
        self.descricao.setToolTip(str(p.raiz))
        self.m_topo.definir(p.projeto.topo, "", f"em {p.raiz.name}/axil.toml")
        self.m_pdk.definir(
            p.asic.pdk.value.replace("skywater", "sky"), "", p.asic.biblioteca_efetiva
        )
        sdc = p.fontes.sdc or "gerado a partir da frequência"
        self.m_relogio.definir(
            fmt.numero(p.asic.frequencia_mhz, 0), "MHz", f"relógio {p.asic.relogio} · SDC {sdc}"
        )
        tb = len(p.fontes.testbenches)
        self.m_fontes.definir(str(len(p.fontes.rtl)), "padrões", f"{tb} padrão(ões) de testbench")
        self.secao_execucao.setVisible(self.executando)
        self.painel.setVisible(self.executando)
        self._atualizar_ultimas()

    def _atualizar_ultimas(self) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            return
        tarefa = tarefas.em_segundo_plano(caderno.listar, self)
        tarefa.concluido.connect(self._mostrar_ultimas)
        tarefa.iniciar()
        self._tarefa_lista = tarefa

    def _mostrar_ultimas(self, registros: list[RegistroExecucao]) -> None:
        for etapa, cartao in self.cartoes.items():
            r = next((x for x in registros if x.etapa is etapa), None)
            if r is None:
                cartao.ultima.setText("Ainda não executada.")
                continue
            texto, _ = tom_da_situacao(r.situacao)
            extra = ""
            m = r.metrica("fmax_mhz")
            if m and r.situacao is Situacao.SUCESSO:
                extra = f" · Fmax {fmt.numero(m.valor, 1)} MHz"
            cartao.ultima.setText(f"ÚLTIMA #{r.numero}: {texto} · {fmt.momento(r.inicio)}{extra}")


def gds_de(r: RegistroExecucao) -> Path | None:
    a = next((x for x in r.artefatos if x.tipo is TipoArtefato.GDS), None)
    return (r.diretorio / a.caminho) if a and r.diretorio else None


__all__ = ["DialogoNovoProjeto", "TelaProjeto", "gds_de"]
