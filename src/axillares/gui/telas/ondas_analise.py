"""Painel de análise da tela Ondas: atividade, medição entre cursores e histograma de valores.

As contas moram em core/atividade.py; aqui só se mostram, em tabela e em barras.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares.core import atividade as at
from axillares.core import formato as fmt
from axillares.gui import tema as t
from axillares.gui.componentes import Tabela, rotulo
from axillares.gui.componentes import segmentos as _segmentos
from axillares.gui.graficos import Barra, GraficoBarras
from axillares.gui.tema import Espaco, Papel
from axillares.gui.visor_ondas import VisorOndas, texto_tempo
from axillares.motor.ondas import formatar

ABAS = (("Atividade", 0), ("Medição", 1), ("Histograma", 2))
EXPLICA_ATIVIDADE = (
    "Atividade é quantas vezes cada sinal troca de valor. Por ciclo de relógio, ela é o fator α "
    "que pesa no consumo: num chip CMOS, cada troca carrega ou descarrega um fio, e a potência "
    "dinâmica é ≈ α · C · V² · f. O relógio tem α = 2 (sobe e desce a cada ciclo)."
)
EXPLICA_MEDICAO = (
    "Clique para pôr o cursor A; Shift+clique ou botão direito para o cursor B. Aqui aparecem o "
    "intervalo entre os dois, a frequência correspondente e o que cada sinal fez nesse trecho. "
    "Esc apaga o cursor B."
)
EXPLICA_HISTOGRAMA = (
    "Quanto tempo o sinal escolhido (a linha destacada) passou em cada valor. Num contador, as "
    "barras se igualam; numa máquina de estados, mostram em que estado ela mais fica."
)


def _hertz(valor: float | None) -> str:
    if not valor:
        return "—"
    for unidade, fator in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if valor >= fator:
            return f"{fmt.numero(valor / fator, 2)} {unidade}"
    return f"{fmt.numero(valor, 1)} Hz"


def _segundos(valor: float | None) -> str:
    return "—" if valor is None else texto_tempo(valor * 1e12)


class PainelAnaliseOndas(QWidget):
    relogio_mudou = Signal(str)

    def __init__(self, visor: VisorOndas) -> None:
        super().__init__()
        self.visor = visor
        self.relogio: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.M + 2, Espaco.S, Espaco.M, Espaco.S)
        lay.setSpacing(Espaco.S)
        topo = QHBoxLayout()
        topo.setSpacing(Espaco.S)
        topo.addWidget(rotulo("Análise", Papel.ROTULO, "3"))
        abas, self._grupo = _segmentos(list(ABAS), self._trocar)
        topo.addLayout(abas)
        topo.addStretch(1)
        topo.addWidget(rotulo("relógio de referência", Papel.ROTULO, "3"))
        self.combo_relogio = QComboBox()
        self.combo_relogio.setFont(t.fonte(Papel.MONO))
        self.combo_relogio.setMinimumWidth(160)
        self.combo_relogio.activated.connect(self._escolheu_relogio)
        topo.addWidget(self.combo_relogio)
        lay.addLayout(topo)
        self.explicacao = rotulo(EXPLICA_ATIVIDADE, Papel.PEQUENO, "2")
        self.explicacao.setWordWrap(True)
        lay.addWidget(self.explicacao)

        self.pilha = QStackedWidget()
        lay.addWidget(self.pilha, 1)
        # atividade: tabela + barras do fator α
        pagina = QWidget()
        pa = QHBoxLayout(pagina)
        pa.setContentsMargins(0, 0, 0, 0)
        pa.setSpacing(Espaco.L)
        self.tabela_atividade = Tabela(
            [("sinal", 4, "e"), ("trocas", 2, "d"), ("α / ciclo", 2, "d"), ("em 1", 2, "d"),
             ("frequência", 3, "d"), ("pulso mín.", 3, "d")],
            [Papel.MONO] * 6,
        )  # fmt: skip
        pa.addWidget(self._rolavel(self.tabela_atividade), 3)
        coluna = QVBoxLayout()
        coluna.addWidget(rotulo("α por ciclo de relógio", Papel.ROTULO, "3"))
        self.grafico_atividade = GraficoBarras(120)
        coluna.addWidget(self.grafico_atividade)
        coluna.addStretch(1)
        pa.addLayout(coluna, 2)
        self.pilha.addWidget(pagina)
        # medição
        pagina = QWidget()
        pm = QVBoxLayout(pagina)
        pm.setContentsMargins(0, 0, 0, 0)
        self.resumo_medicao = rotulo("", Papel.CORPO_FORTE)
        pm.addWidget(self.resumo_medicao)
        self.tabela_medicao = Tabela(
            [("sinal", 4, "e"), ("em A", 2, "d"), ("em B", 2, "d"), ("trocas entre", 2, "d")],
            [Papel.MONO] * 4,
        )
        pm.addWidget(self._rolavel(self.tabela_medicao), 1)
        self.pilha.addWidget(pagina)
        # histograma
        pagina = QWidget()
        ph = QVBoxLayout(pagina)
        ph.setContentsMargins(0, 0, 0, 0)
        self.titulo_histograma = rotulo("", Papel.CORPO_FORTE)
        ph.addWidget(self.titulo_histograma)
        self.grafico_histograma = GraficoBarras(120)
        ph.addWidget(self._rolavel(self.grafico_histograma), 1)
        self.pilha.addWidget(pagina)

    @staticmethod
    def _rolavel(conteudo: QWidget) -> QScrollArea:
        r = QScrollArea()
        r.setWidgetResizable(True)
        r.setFrameShape(QScrollArea.Shape.NoFrame)
        r.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        r.setWidget(conteudo)
        return r

    def _trocar(self, indice: object) -> None:
        i = int(indice)
        self.pilha.setCurrentIndex(i)
        self._grupo.button(i).setChecked(True)
        self.explicacao.setText((EXPLICA_ATIVIDADE, EXPLICA_MEDICAO, EXPLICA_HISTOGRAMA)[i])
        self.atualizar()

    def _escolheu_relogio(self, _i: int) -> None:
        self.relogio = self.combo_relogio.currentData()
        self.atualizar()

    def preparar(self) -> None:
        """Nova onda: escolhe o relógio de referência (pelo nome ou pelo mais periódico)."""
        onda = self.visor.onda
        self.combo_relogio.clear()
        if onda is None:
            return
        um_bit = [s for s in onda.sinais if s.largura == 1]
        candidatos = [(s.nome_completo, s.largura, onda.mudancas(s.nome_completo)) for s in um_bit]
        self.relogio = at.relogio_de_referencia(candidatos)
        self.combo_relogio.addItem("— nenhum —", None)
        for s in um_bit:
            self.combo_relogio.addItem(s.nome_completo, s.nome_completo)
        self.combo_relogio.setCurrentIndex(max(0, self.combo_relogio.findData(self.relogio)))
        self.atualizar()

    @property
    def _segundos_por_unidade(self) -> float:
        onda = self.visor.onda
        return onda.em_ps(1) * 1e-12 if onda else 1e-12

    def atualizar(self) -> None:
        if self.visor.onda is None or not self.isVisible():
            return
        [self._atividade, self._medicao, self._histograma][self.pilha.currentIndex()]()

    def _sinais(self):
        onda = self.visor.onda
        por_nome = {s.nome_completo: s for s in onda.sinais}
        return [por_nome[n] for n in self.visor.linhas if n in por_nome]

    def _atividade(self) -> None:
        onda = self.visor.onda
        ciclos = None
        if self.relogio:
            ciclos = at.analisar(self.relogio, 1, onda.mudancas(self.relogio), onda.fim,
                                 self._segundos_por_unidade).subidas or None  # fmt: skip
        self.tabela_atividade.limpar()
        analises = []
        for s in self._sinais():
            a = at.analisar(s.nome_completo, s.largura, onda.mudancas(s.nome_completo), onda.fim,
                            self._segundos_por_unidade, ciclos)  # fmt: skip
            analises.append((s, a))
            self.tabela_atividade.adicionar(
                [s.nome + (f"[{s.largura - 1}:0]" if s.largura > 1 else ""),
                 str(a.transicoes),
                 fmt.numero(a.por_ciclo, 2) if a.por_ciclo is not None else "—",
                 f"{fmt.numero(a.alto_pct, 0)} %" if a.alto_pct is not None else "—",
                 _hertz(a.frequencia_hz) if a.periodico else "—",
                 _segundos(a.pulso_min_s)],
                tons=[None, None, None, "2", "2", "2"],
            )  # fmt: skip
        if not analises:
            self.tabela_atividade.mostrar_vazio("Marque sinais na lista à esquerda.")
        chave = (lambda a: a.por_ciclo) if ciclos else (lambda a: float(a.transicoes))
        maior = max((chave(a) or 0.0 for _s, a in analises), default=0.0) or 1.0
        barras = [Barra(s.nome, (chave(a) or 0.0) / maior,
                        fmt.numero(chave(a) or 0.0, 2 if ciclos else 0),
                        self.visor.cor_de(s.nome_completo)) for s, a in analises]  # fmt: skip
        self.grafico_atividade.definir(barras, "Sem sinais.")

    def _medicao(self) -> None:
        onda = self.visor.onda
        a, b = self.visor.cursor, self.visor.cursor_b
        self.tabela_medicao.limpar()
        if a is None or b is None:
            self.resumo_medicao.setText("Ponha os dois cursores: clique (A) e Shift+clique (B).")
            return
        delta = abs(onda.em_ps(b) - onda.em_ps(a))
        frequencia = 1e12 / delta if delta else None
        self.resumo_medicao.setText(
            f"A {texto_tempo(onda.em_ps(a))}  ·  B {texto_tempo(onda.em_ps(b))}  ·  "
            f"Δt = {texto_tempo(delta)}  ·  1/Δt = {_hertz(frequencia)}"
        )
        for s in self._sinais():
            mudancas = onda.mudancas(s.nome_completo)
            self.tabela_medicao.adicionar(
                [s.nome, formatar(onda.valor_em(s.nome_completo, a), s.largura, self.visor.base),
                 formatar(onda.valor_em(s.nome_completo, b), s.largura, self.visor.base),
                 str(at.entre(mudancas, a, b))],
                tons=[None, None, None, "2"],
            )  # fmt: skip

    def _histograma(self) -> None:
        onda = self.visor.onda
        if self.visor.escolhida is None or not self.visor.linhas:
            self.titulo_histograma.setText("Escolha um sinal (clique na linha dele).")
            self.grafico_histograma.definir([])
            return
        nome = self.visor.linhas[self.visor.escolhida]
        s = next(x for x in onda.sinais if x.nome_completo == nome)
        partes = at.histograma(onda.mudancas(nome), onda.fim)[:24]
        total = sum(d for _v, d in partes) or 1
        self.titulo_histograma.setText(f"{nome} — tempo em cada valor")
        cor = self.visor.cor_de(nome)
        barras = [Barra(formatar(v, s.largura, self.visor.base), d / total,
                        f"{fmt.numero(100 * d / total, 1)} %", cor) for v, d in partes]  # fmt: skip
        self.grafico_histograma.definir(barras, "Sem valores.")
