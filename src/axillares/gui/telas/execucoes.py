"""Telas 4 e 5 — lista de execuções (com filtro) e detalhe de uma execução."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares.ambiente.abrir import abrir as abrir_visualizador
from axillares.core import formato as fmt
from axillares.core.caderno import RegistroExecucao
from axillares.core.modelos import Etapa, Situacao, TipoArtefato
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import (
    Metrica,
    NumeroSecao,
    Pilula,
    Tabela,
    botao,
    cabecalho_tela,
    layout_de_tela,
    quadro,
    rotulo,
    tela_rolavel,
    tom_da_situacao,
)
from axillares.gui.sessao import Sessao
from axillares.gui.telas.abertura import CartaoDiagnostico
from axillares.gui.tema import Espaco, Papel


def _segmentos(opcoes: list[tuple[str, object]], ao_mudar) -> tuple[QHBoxLayout, QButtonGroup]:
    lay = QHBoxLayout()
    lay.setSpacing(0)
    grupo = QButtonGroup(lay)
    for i, (texto, valor) in enumerate(opcoes):
        b = QPushButton(texto)
        b.setProperty("tipo", "segmento")
        b.setProperty("posicao", "inicio" if i == 0 else "fim" if i == len(opcoes) - 1 else "meio")
        b.setFont(t.fonte(Papel.ETIQUETA))
        b.setCheckable(True)
        b.setChecked(i == 0)
        b.setMinimumWidth(72)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _c=False, v=valor: ao_mudar(v))
        grupo.addButton(b, i)
        lay.addWidget(b)
    return lay, grupo


# --- lista ------------------------------------------------------------------------------------


class ListaExecucoes(QWidget):
    abrir = Signal(str)
    comparar = Signal(str, str)

    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self._filtro: Etapa | None = None
        self._marcadas: list[str] = []
        self._registros: list[RegistroExecucao] = []
        w = QWidget()
        lay = layout_de_tela(w)
        cab, self.titulo = cabecalho_tela(
            "Caderno de execuções",
            f"Cada execução, {t.serifa('guardada', tamanho_px=54)}.",
            "Toda execução vira um diretório imutável em runs/, com log, artefatos e métricas. "
            "Clique numa linha para ver o detalhe; marque duas para comparar.",
        )
        lay.addLayout(cab)

        barra = QHBoxLayout()
        segmentos, self._grupo = _segmentos(
            [("Todas", None), ("Síntese", Etapa.SINTESE), ("GDS", Etapa.GDS)], self._filtrar
        )
        barra.addLayout(segmentos)
        barra.addStretch(1)
        self.contagem = rotulo("", Papel.ROTULO, "3")
        barra.addWidget(self.contagem)
        barra.addSpacing(Espaco.M)
        self.botao_comparar = botao("Comparar selecionadas", "primario")
        self.botao_comparar.setEnabled(False)
        self.botao_comparar.clicked.connect(
            lambda: self.comparar.emit(self._marcadas[0], self._marcadas[1])
        )
        barra.addWidget(self.botao_comparar)
        lay.addLayout(barra)

        self.tabela = Tabela(
            [("", 1, "e"), ("#", 1, "e"), ("etapa", 2, "e"), ("situação", 4, "e"),
             ("início", 2, "e"), ("duração", 2, "d"), ("Fmax MHz", 2, "d"),
             ("área µm²", 2, "d"), ("células", 2, "d"), ("folga ns", 2, "d"), ("RTL", 2, "e")],
            [Papel.CORPO, Papel.CORPO_FORTE, Papel.CORPO, Papel.CORPO, Papel.MONO, Papel.MONO,
             Papel.MONO, Papel.MONO, Papel.MONO, Papel.MONO, Papel.MONO],
        )  # fmt: skip
        lay.addWidget(self.tabela)
        legenda = rotulo("≡ MESMO RTL QUE OUTRA EXECUÇÃO DA LISTA", Papel.ROTULO, "3")
        lay.addWidget(legenda)
        lay.addStretch(1)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addWidget(tela_rolavel(w))
        sessao.execucoes_mudaram.connect(self.recarregar)
        sessao.projeto_mudou.connect(lambda _p: self.recarregar())

    def _filtrar(self, etapa: Etapa | None) -> None:
        self._filtro = etapa
        self.recarregar()

    def recarregar(self) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            self.tabela.mostrar_vazio("Abra um projeto para ver as execuções dele.")
            return
        filtro = self._filtro
        self._tarefa = tarefas.em_segundo_plano(lambda: caderno.listar(filtro), self)
        self._tarefa.concluido.connect(self._mostrar)
        self._tarefa.iniciar()

    def _mostrar(self, registros: list[RegistroExecucao]) -> None:
        self._registros = registros
        self._marcadas = [m for m in self._marcadas if any(r.id == m for r in registros)]
        self.tabela.limpar()
        n = len(registros)
        self.contagem.setText(f"{n} EXECUÇ{'ÃO' if n == 1 else 'ÕES'}")
        if not registros:
            self.tabela.mostrar_vazio("Nenhuma execução ainda. Vá em Projeto e execute uma etapa.")
            self._atualizar_botao()
            return
        hashes = [r.hash_rtl for r in registros]
        for r in registros:
            marca = QCheckBox()
            marca.setChecked(r.id in self._marcadas)
            marca.toggled.connect(lambda v, i=r.id: self._marcar(i, v))
            texto, token = tom_da_situacao(r.situacao)
            celulas = [
                marca, f"#{r.numero}", r.etapa.value, Pilula(texto, token),
                fmt.momento(r.inicio), fmt.duracao(r.duracao_s),
            ]  # fmt: skip
            for chave, casas in (("fmax_mhz", 1), ("area_total_um2", 1), ("celulas", 0),
                                 ("folga_setup_ns", 2)):  # fmt: skip
                m = r.metrica(chave)
                celulas.append(fmt.numero(m.valor, casas) if m else "—")
            igual = "≡ " if hashes.count(r.hash_rtl) > 1 else "  "
            celulas.append(f"{igual}{r.hash_curto}")
            self.tabela.adicionar(
                celulas,
                ao_clicar=lambda i=r.id: self.abrir.emit(i),
                tons=[None, None, None, None, "2", "2", None, None, None, None, "3"],
            )
        self._atualizar_botao()

    def _marcar(self, ident: str, marcada: bool) -> None:
        if marcada and ident not in self._marcadas:
            self._marcadas.append(ident)
            if len(self._marcadas) > 2:
                self._marcadas.pop(0)
                self._mostrar(self._registros)
                return
        elif not marcada and ident in self._marcadas:
            self._marcadas.remove(ident)
        self._atualizar_botao()

    def _atualizar_botao(self) -> None:
        self.botao_comparar.setEnabled(len(self._marcadas) == 2)


# --- detalhe ----------------------------------------------------------------------------------


class DetalheExecucao(QWidget):
    voltar = Signal()

    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self.registro: RegistroExecucao | None = None
        w = QWidget()
        self.lay = layout_de_tela(w)
        volta = botao("←  Execuções", "link")
        volta.setFont(t.fonte(Papel.NAV))
        volta.clicked.connect(self.voltar)
        self.lay.addWidget(volta, 0, Qt.AlignmentFlag.AlignLeft)

        topo = QHBoxLayout()
        cab, self.titulo = cabecalho_tela("Execução", "")
        self.eyebrow = cab.itemAt(0).widget()
        topo.addLayout(cab, 1)
        lado = QVBoxLayout()
        lado.addStretch(1)
        self.pilula = Pilula("", "tinta_3")
        lado.addWidget(self.pilula, 0, Qt.AlignmentFlag.AlignRight)
        acoes = QHBoxLayout()
        self.botao_gds = botao("Abrir GDS no KLayout", "primario")
        self.botao_gds.clicked.connect(self._abrir_gds)
        self.botao_pasta = botao("Mostrar na pasta", "fantasma")
        self.botao_pasta.clicked.connect(self._abrir_pasta)
        acoes.addWidget(self.botao_pasta)
        acoes.addWidget(self.botao_gds)
        lado.addLayout(acoes)
        topo.addLayout(lado)
        self.lay.addLayout(topo)

        self.aviso = QVBoxLayout()
        self.lay.addLayout(self.aviso)

        grade = quadro("grade")
        g = QHBoxLayout(grade)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(1)
        self.celulas = {
            "fmax_mhz": Metrica("Frequência máxima"),
            "area_total_um2": Metrica("Área total"),
            "celulas": Metrica("Células"),
            "folga_setup_ns": Metrica("Folga de setup"),
        }
        for m in self.celulas.values():
            g.addWidget(m, 1)
        self.grade = grade
        self.lay.addWidget(grade)

        self.lay.addWidget(NumeroSecao("01", "Métricas", "TRADUZIDAS DO MANIFESTO DO MOTOR"))
        self.metricas = Tabela(
            [("métrica", 5, "e"), ("valor", 3, "d"), ("unidade", 2, "e"), ("origem", 4, "e")],
            [Papel.CORPO, Papel.MONO, Papel.MONO, Papel.MONO],
        )
        self.lay.addWidget(self.metricas)

        self.lay.addWidget(NumeroSecao("02", "Artefatos", "EM saida/"))
        self.artefatos = Tabela(
            [("arquivo", 5, "e"), ("tipo", 2, "e"), ("tamanho", 2, "d"), ("", 3, "d")],
            [Papel.MONO, Papel.ETIQUETA, Papel.MONO, Papel.CORPO],
        )
        self.lay.addWidget(self.artefatos)

        self.lay.addWidget(NumeroSecao("03", "Registro", "meta.json"))
        self.meta = rotulo("", Papel.MONO, "2", rico=True)
        self.meta.setWordWrap(True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(self.meta)

        self.lay.addWidget(NumeroSecao("04", "Log", "log.txt — COMPLETO"))
        self.log = QPlainTextEdit()
        self.log.setProperty("tipo", "log")
        self.log.setReadOnly(True)
        self.log.setFont(t.fonte(Papel.MONO))
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setMinimumHeight(320)
        self.lay.addWidget(self.log)
        self.lay.addStretch(1)

        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addWidget(tela_rolavel(w))

    def carregar(self, ident: str) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            return

        def ler() -> tuple[RegistroExecucao, str]:
            r = caderno.carregar(ident)
            log = (r.diretorio / "log.txt").read_text(encoding="utf-8", errors="replace")
            return r, log

        self._tarefa = tarefas.em_segundo_plano(ler, self)
        self._tarefa.concluido.connect(lambda par: self.mostrar(*par))
        self._tarefa.falhou.connect(self.sessao.erro)
        self._tarefa.iniciar()

    def mostrar(self, r: RegistroExecucao, log: str) -> None:
        self.registro = r
        pal = t.paleta()
        self.eyebrow.texto.setText(f"#{r.numero} · {r.etapa.value} · {r.id}".upper())
        self.titulo.setText(f"Execução #{r.numero}")
        texto, token = tom_da_situacao(r.situacao)
        self.pilula.definir(texto, token)
        self.botao_gds.setVisible(self._gds() is not None)

        while self.aviso.count():
            item = self.aviso.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if r.falha and r.situacao is not Situacao.SUCESSO:
            from axillares.ambiente.diagnostico import Diagnostico, Gravidade

            self.aviso.addWidget(
                CartaoDiagnostico(
                    Diagnostico(
                        codigo=r.falha.passo or r.situacao.value,
                        o_que=r.falha.resumo,
                        por_que="O motor apontou:" if r.falha.mensagens else "",
                        proximo_passo=r.falha.proximo_passo or "Veja o log abaixo.",
                        gravidade=Gravidade.BLOQUEANTE
                        if r.situacao is Situacao.FALHA
                        else Gravidade.AVISO,
                    ),
                    mensagens=r.falha.mensagens,
                )
            )

        for chave, celula in self.celulas.items():
            m = r.metrica(chave)
            if m:
                celula.definir(fmt.numero(m.valor, fmt.casas_para(chave, m.valor)), m.unidade,
                               f"medida em {m.origem}" if m.origem else "")  # fmt: skip
            else:
                celula.definir("—", "", "não produzida nesta etapa")

        self.metricas.limpar()
        if not r.metricas:
            self.metricas.mostrar_vazio("Esta execução não produziu métricas.")
        for m in r.metricas:
            casas = fmt.casas_para(m.chave, m.valor)
            self.metricas.adicionar(
                [m.rotulo or m.chave, fmt.numero(m.valor, casas), m.unidade or "—", m.origem],
                tons=[None, None, "2", "3"],
            )

        self.artefatos.limpar()
        if not r.artefatos:
            self.artefatos.mostrar_vazio("Nenhum artefato guardado.")
        for a in r.artefatos:
            acao: QWidget | str = ""
            if a.tipo is TipoArtefato.GDS:
                b = botao("Abrir no KLayout", "link")
                b.clicked.connect(self._abrir_gds)
                acao = b
            self.artefatos.adicionar(
                [a.caminho.as_posix(), a.tipo.value, fmt.tamanho(a.bytes), acao],
                tons=[None, "2", "2", None],
            )

        linhas = [
            ("motor", f"{r.motor} {r.versao_motor}"),
            ("início", f"{r.inicio:%d/%m/%Y %H:%M:%S}"),
            ("duração", fmt.duracao(r.duracao_s)),
            ("hash do RTL", r.hash_rtl),
            ("axillares", r.axillares),
            ("comando", " ".join(r.comando) if r.comando else "—"),
        ]
        self.meta.setText(
            "<br>".join(
                f"<span style='color:{pal.tinta_3}'>{k.upper():<12}</span>&nbsp;&nbsp;"
                f"{html.escape(v)}"
                for k, v in linhas
            )
        )
        self.log.setPlainText(log)

    def _gds(self) -> Path | None:
        r = self.registro
        if r is None or r.diretorio is None:
            return None
        a = next((x for x in r.artefatos if x.tipo is TipoArtefato.GDS), None)
        return r.diretorio / a.caminho if a else None

    def _abrir_gds(self) -> None:
        gds = self._gds()
        if gds is None:
            return
        diag = abrir_visualizador(gds, "gds")
        if diag is not None:
            while self.aviso.count():
                item = self.aviso.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.aviso.addWidget(CartaoDiagnostico(diag))

    def _abrir_pasta(self) -> None:
        if self.registro and self.registro.diretorio:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.registro.diretorio)))


class TelaExecucoes(QWidget):
    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pilha = QStackedWidget()
        lay.addWidget(self.pilha)
        self.lista = ListaExecucoes(sessao)
        self.detalhe = DetalheExecucao(sessao)
        self.pilha.addWidget(self.lista)
        self.pilha.addWidget(self.detalhe)
        self.lista.abrir.connect(self.abrir)
        self.detalhe.voltar.connect(lambda: self.pilha.setCurrentIndex(0))

    def abrir(self, ident: str) -> None:
        self.detalhe.carregar(ident)
        self.pilha.setCurrentIndex(1)


__all__ = ["TelaExecucoes"]
