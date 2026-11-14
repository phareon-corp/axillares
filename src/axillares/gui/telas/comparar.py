"""Tela 6 — comparação de duas execuções. Usa a mesma função de `axil comparar`."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from axillares.core import formato as fmt
from axillares.core.caderno import Caderno, RegistroExecucao
from axillares.core.comparacao import Comparacao, comparar
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import (
    Eyebrow,
    NumeroSecao,
    Tabela,
    cabecalho_tela,
    layout_de_tela,
    rotulo,
    tela_rolavel,
)
from axillares.gui.sessao import Sessao
from axillares.gui.tema import Espaco, Papel

TOM_TENDENCIA = {"melhor": "ok", "pior": "falha", "igual": "3", "neutra": None}


class TelaComparar(QWidget):
    def __init__(self, sessao: Sessao) -> None:
        super().__init__()
        self.sessao = sessao
        self._registros: list[RegistroExecucao] = []
        self._pedido: tuple[str, str] | None = None
        w = QWidget()
        lay = layout_de_tela(w)
        cab, _ = cabecalho_tela(
            "Comparar",
            f"O que {t.serifa('mudou', tamanho_px=54)} de uma execução para outra.",
            "Diferença absoluta e percentual de cada métrica. Verde: melhorou de A para B; "
            "vermelho: piorou. Se o RTL for o mesmo, a diferença veio de restrições ou do motor.",
        )
        lay.addLayout(cab)

        seletores = QHBoxLayout()
        seletores.setSpacing(Espaco.L)
        self.combo_a = QComboBox()
        self.combo_b = QComboBox()
        for nome, combo in (("A", self.combo_a), ("B", self.combo_b)):
            caixa = QVBoxLayout()
            caixa.setSpacing(6)
            caixa.addWidget(rotulo(f"Execução {nome}", Papel.ROTULO, "3"))
            combo.setFont(t.fonte(Papel.MONO))
            combo.setMinimumWidth(320)
            combo.currentIndexChanged.connect(self._calcular)
            caixa.addWidget(combo)
            seletores.addLayout(caixa)
        seletores.addStretch(1)
        lay.addLayout(seletores)

        self.notas = QVBoxLayout()
        self.notas.setSpacing(6)
        lay.addLayout(self.notas)

        lay.addWidget(NumeroSecao("01", "Métricas", "A → B"))
        self.tabela = Tabela(
            [("métrica", 6, "e"), ("A", 3, "d"), ("B", 3, "d"), ("Δ", 3, "d"), ("Δ %", 2, "d")],
            [Papel.CORPO, Papel.MONO, Papel.MONO, Papel.MONO, Papel.MONO],
        )
        lay.addWidget(self.tabela)
        lay.addStretch(1)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addWidget(tela_rolavel(w))
        sessao.execucoes_mudaram.connect(self.recarregar)
        sessao.projeto_mudou.connect(lambda _p: self.recarregar())

    def pedir(self, a: str, b: str) -> None:
        """Pré-seleciona A e B (vindo da lista de execuções)."""
        self._pedido = (a, b)
        self.recarregar()

    def recarregar(self) -> None:
        caderno = self.sessao.caderno
        if caderno is None:
            self.tabela.mostrar_vazio("Abra um projeto para comparar execuções.")
            return

        def ler(c: Caderno = caderno) -> list[RegistroExecucao]:
            return [c.carregar(r.id) for r in c.listar()]

        self._tarefa = tarefas.em_segundo_plano(ler, self)
        self._tarefa.concluido.connect(self._preencher)
        self._tarefa.iniciar()

    def _preencher(self, registros: list[RegistroExecucao]) -> None:
        self._registros = registros
        for combo in (self.combo_a, self.combo_b):
            combo.blockSignals(True)
            combo.clear()
            for r in registros:
                texto, _ = fmt.ROTULO_SITUACAO[r.situacao], None
                combo.addItem(
                    f"#{r.numero}  {r.etapa.value:<8} {texto:<12} {fmt.momento(r.inicio)}", r.id
                )
            combo.blockSignals(False)
        if len(registros) < 2:
            self.tabela.mostrar_vazio("São precisas pelo menos duas execuções para comparar.")
            return
        a, b = (registros[1].id, registros[0].id)  # penúltima → última
        if self._pedido:
            a, b = sorted(self._pedido, key=lambda i: [r.id for r in registros].index(i),
                          reverse=True)  # fmt: skip
            self._pedido = None
        self.combo_a.setCurrentIndex(self.combo_a.findData(a))
        self.combo_b.setCurrentIndex(self.combo_b.findData(b))
        self._calcular()

    def _calcular(self, *_: object) -> None:
        por_id = {r.id: r for r in self._registros}
        a, b = por_id.get(self.combo_a.currentData()), por_id.get(self.combo_b.currentData())
        if a is None or b is None:
            return
        self.mostrar(comparar(a, b))

    def mostrar(self, c: Comparacao) -> None:
        while self.notas.count():
            item = self.notas.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if c.mesmo_rtl:
            self.notas.addWidget(Eyebrow(f"Mesmo RTL · hash {c.a.hash_curto}", "ok"))
        else:
            self.notas.addWidget(
                Eyebrow(f"RTL diferente · {c.a.hash_curto} → {c.b.hash_curto}", "aviso")
            )
        if not c.mesma_etapa:
            self.notas.addWidget(
                Eyebrow("Etapas diferentes: nem toda métrica é comparável", "aviso")
            )
        if not c.mesma_versao_motor:
            self.notas.addWidget(Eyebrow("Versões de motor diferentes", "aviso"))

        self.tabela.limpar()
        for linha in c.linhas:
            casas = fmt.casas_para(linha.chave, linha.a, linha.b)
            tom = TOM_TENDENCIA[linha.tendencia]
            pct = (
                fmt.numero(linha.delta_pct, 1, sinal=True) + " %"
                if linha.delta_pct is not None
                else "—"
            )
            unidade = f"  ({linha.unidade})" if linha.unidade else ""
            self.tabela.adicionar(
                [f"{linha.rotulo}{unidade}", fmt.numero(linha.a, casas),
                 fmt.numero(linha.b, casas), fmt.numero(linha.delta, casas, sinal=True), pct],
                tons=[None, "2", None, tom, tom],
            )  # fmt: skip
