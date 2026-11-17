"""Painel de simulação do esquemático: entradas, relógio e a linha do tempo para reproduzir.

O tempo anda em meios ciclos (relógio baixo, relógio alto), que é o que um circuito síncrono
precisa para ser entendido: as entradas mudam com o relógio baixo e os registradores guardam o
valor novo na borda de subida. Mudar uma entrada vale a partir do ciclo mostrado — e a simulação
roda de novo sozinha.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from axillares.core.esquema import PortaModulo
from axillares.core.simulacao_esquema import Estimulo, eh_reset
from axillares.gui import tema as t
from axillares.gui.componentes import botao, rotulo
from axillares.gui.tema import Espaco, Papel

VELOCIDADES = (("½×", 1200), ("1×", 600), ("2×", 300), ("4×", 150))


class ControleEntrada(QWidget):
    """Uma entrada do módulo: chave 0/1 (1 bit) ou número (barramento)."""

    mudou = Signal(str, int)

    def __init__(self, porta: PortaModulo) -> None:
        super().__init__()
        self.porta = porta
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        nome = rotulo(porta.nome, Papel.MONO)
        lay.addWidget(nome)
        if porta.largura == 1:
            self.chave = QPushButton("0")
            self.chave.setCheckable(True)
            self.chave.setProperty("tipo", "compacto")
            self.chave.setFont(t.fonte(Papel.MONO))
            self.chave.setFixedWidth(34)
            self.chave.setCursor(Qt.CursorShape.PointingHandCursor)
            self.chave.setToolTip(
                "Troca o valor a partir do ciclo mostrado"
                + (" — é um reset: ativo no começo, para o circuito partir do zero."
                   if eh_reset(porta.nome) else "")
            )  # fmt: skip
            self.chave.clicked.connect(lambda c: self.mudou.emit(porta.nome, int(c)))
            lay.addWidget(self.chave)
            self.campo = None
        else:
            self.chave = None
            self.campo = QLineEdit("0")
            self.campo.setFont(t.fonte(Papel.MONO))
            self.campo.setFixedWidth(max(60, 9 * ((porta.largura + 3) // 4) + 34))
            self.campo.setToolTip(
                f"{porta.largura} bits: decimal (12), hexadecimal (0x0C) ou binário (0b1100)"
            )
            self.campo.editingFinished.connect(self._editou)
            lay.addWidget(self.campo)

    def _editou(self) -> None:
        assert self.campo is not None
        texto = self.campo.text().strip().lower().replace("_", "")
        try:
            valor = int(texto, 0)
        except ValueError:
            return
        valor &= (1 << self.porta.largura) - 1
        self.mudou.emit(self.porta.nome, valor)

    def mostrar(self, valor: int) -> None:
        if self.chave is not None:
            self.chave.blockSignals(True)
            self.chave.setChecked(bool(valor))
            self.chave.setText(str(valor & 1))
            self.chave.blockSignals(False)
        elif self.campo is not None and not self.campo.hasFocus():
            digitos = (self.porta.largura + 3) // 4
            self.campo.setText(f"0x{valor:0{digitos}X}")


class PainelSimulacao(QFrame):
    estimulo_mudou = Signal(object)
    """O estímulo mudou (entradas, relógio, período ou ciclos): simular de novo."""
    tempo_mudou = Signal(float)
    """Instante a mostrar, em ns."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("tipo", "barra-abas")
        self.estimulo = Estimulo()
        self.portas: list[PortaModulo] = []
        self.controles: dict[str, ControleEntrada] = {}
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._tique)
        col = QVBoxLayout(self)
        col.setContentsMargins(Espaco.M + 2, 6, Espaco.M, 6)
        col.setSpacing(6)

        # linha 1: reprodução
        linha = QHBoxLayout()
        linha.setSpacing(Espaco.S)
        self.botoes = {}
        for chave, texto, dica, acao in (
            ("inicio", "⏮", "Voltar ao início", lambda: self.ir(0)),
            ("voltar", "◀", "Meio ciclo para trás (←)", lambda: self.passo(-1)),
            ("tocar", "▶", "Reproduzir / pausar (espaço)", self.alternar),
            ("avancar", "▶|", "Meio ciclo para a frente (→)", lambda: self.passo(1)),
            ("fim", "⏭", "Ir ao fim", lambda: self.ir(self.slider.maximum())),
        ):
            b = botao(texto, "compacto")
            b.setToolTip(dica)
            b.clicked.connect(acao)
            self.botoes[chave] = b
            linha.addWidget(b)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._slider_mudou)
        linha.addWidget(self.slider, 1)
        self.instante = rotulo("", Papel.MONO)
        self.instante.setMinimumWidth(250)
        linha.addWidget(self.instante)
        self.velocidade = QComboBox()
        self.velocidade.setFont(t.fonte(Papel.PEQUENO))
        for texto, ms in VELOCIDADES:
            self.velocidade.addItem(texto, ms)
        self.velocidade.setCurrentIndex(1)
        self.velocidade.setToolTip("Velocidade da reprodução")
        self.velocidade.setFixedWidth(64)
        self.velocidade.currentIndexChanged.connect(self._ajustar_velocidade)
        linha.addWidget(self.velocidade)
        col.addLayout(linha)

        # linha 2: relógio e entradas
        linha2 = QHBoxLayout()
        linha2.setSpacing(Espaco.S)
        linha2.addWidget(rotulo("Relógio", Papel.ROTULO, "3"))
        self.combo_relogio = QComboBox()
        self.combo_relogio.setFont(t.fonte(Papel.MONO))
        self.combo_relogio.setToolTip("Entrada que recebe o relógio (onda quadrada)")
        self.combo_relogio.setMinimumWidth(110)
        self.combo_relogio.activated.connect(self._relogio_escolhido)
        linha2.addWidget(self.combo_relogio)
        self.periodo = QDoubleSpinBox()
        self.periodo.setRange(0.1, 1e6)
        self.periodo.setDecimals(1)
        self.periodo.setSuffix(" ns")
        self.periodo.setValue(10.0)
        self.periodo.setToolTip("Período do relógio (10 ns = 100 MHz)")
        self.periodo.setFixedWidth(96)
        self.periodo.editingFinished.connect(self._configuracao)
        linha2.addWidget(self.periodo)
        self.frequencia = rotulo("", Papel.PEQUENO, "3")
        linha2.addWidget(self.frequencia)
        self.ciclos = QSpinBox()
        self.ciclos.setRange(1, 2000)
        self.ciclos.setValue(16)
        self.ciclos.setSuffix(" ciclos")
        self.ciclos.setFixedWidth(104)
        self.ciclos.editingFinished.connect(self._configuracao)
        linha2.addWidget(self.ciclos)
        linha2.addSpacing(Espaco.S)
        linha2.addWidget(rotulo("Entradas", Papel.ROTULO, "3"))
        rolagem = QScrollArea()
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setWidgetResizable(True)
        rolagem.setFixedHeight(34)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rolagem.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        caixa = QWidget()
        self._entradas = QHBoxLayout(caixa)
        self._entradas.setContentsMargins(0, 0, 0, 0)
        self._entradas.setSpacing(Espaco.M)
        self._entradas.addStretch(1)
        rolagem.setWidget(caixa)
        linha2.addWidget(rolagem, 1)
        self.situacao = QLabel()
        self.situacao.setFont(t.fonte(Papel.PEQUENO))
        self.situacao.setProperty("tom", "3")
        linha2.addWidget(self.situacao)
        col.addLayout(linha2)

    # --- configuração --------------------------------------------------------------------------

    def configurar(self, portas: list[PortaModulo], estimulo: Estimulo) -> None:
        self.portas = [p for p in portas if p.direcao == "entrada" and p.alimentacao is None]
        self.estimulo = estimulo
        self.combo_relogio.blockSignals(True)
        self.combo_relogio.clear()
        self.combo_relogio.addItem("(sem relógio)", None)
        for p in self.portas:
            if p.largura == 1:
                self.combo_relogio.addItem(p.nome, p.nome)
        self.combo_relogio.setCurrentIndex(max(0, self.combo_relogio.findData(estimulo.relogio)))
        self.combo_relogio.blockSignals(False)
        self.periodo.setValue(estimulo.periodo_ns)
        self.ciclos.setValue(estimulo.ciclos)
        self._montar_controles()
        self.slider.setMaximum(2 * estimulo.ciclos - 1)
        self._atualizar_frequencia()
        self._slider_mudou(self.slider.value())

    def _montar_controles(self) -> None:
        while self._entradas.count() > 1:
            item = self._entradas.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.controles = {}
        for p in self.portas:
            if p.nome == self.estimulo.relogio:
                continue
            c = ControleEntrada(p)
            c.mudou.connect(self._entrada_mudou)
            self.controles[p.nome] = c
            self._entradas.insertWidget(self._entradas.count() - 1, c)
        self._mostrar_entradas()

    def _relogio_escolhido(self, _i: int) -> None:
        self.estimulo.relogio = self.combo_relogio.currentData()
        self._montar_controles()
        self.estimulo_mudou.emit(self.estimulo)

    def _configuracao(self) -> None:
        mudou = (self.estimulo.periodo_ns != self.periodo.value()
                 or self.estimulo.ciclos != self.ciclos.value())  # fmt: skip
        if not mudou:
            return
        self.estimulo.periodo_ns = self.periodo.value()
        self.estimulo.ciclos = self.ciclos.value()
        self.slider.setMaximum(2 * self.estimulo.ciclos - 1)
        self._atualizar_frequencia()
        self.estimulo_mudou.emit(self.estimulo)

    def _atualizar_frequencia(self) -> None:
        mhz = 1000.0 / self.estimulo.periodo_ns
        texto = f"{mhz:g} MHz" if mhz < 1000 else f"{mhz / 1000:g} GHz"
        self.frequencia.setText(texto if self.estimulo.relogio else "")

    # --- entradas ------------------------------------------------------------------------------

    @property
    def ciclo(self) -> int:
        return self.slider.value() // 2

    def _entrada_mudou(self, porta: str, valor: int) -> None:
        self.estimulo.definir(porta, self.ciclo, valor)
        self._mostrar_entradas()
        self.estimulo_mudou.emit(self.estimulo)

    def alternar_entrada(self, porta: str) -> None:
        """Clique numa entrada no desenho: 1 bit troca; barramento soma 1."""
        p = next((x for x in self.portas if x.nome == porta), None)
        if p is None or porta == self.estimulo.relogio:
            return
        atual = self.estimulo.valor(porta, self.ciclo)
        novo = (1 - atual) if p.largura == 1 else (atual + 1) % (1 << p.largura)
        self._entrada_mudou(porta, novo)

    def _mostrar_entradas(self) -> None:
        for nome, c in self.controles.items():
            c.mostrar(self.estimulo.valor(nome, self.ciclo))

    # --- tempo ---------------------------------------------------------------------------------

    def t_ns(self) -> float:
        """Meio do meio ciclo mostrado: o estado depois das bordas daquele instante."""
        meio = self.estimulo.periodo_ns / 2
        return self.slider.value() * meio + meio * 0.5

    def _slider_mudou(self, valor: int) -> None:
        e = self.estimulo
        fase = "relógio em 1 (depois da borda ↑)" if valor % 2 else "relógio em 0"
        if not e.relogio:
            fase = "passo"
        self.instante.setText(f"ciclo {valor // 2 + 1}/{e.ciclos} · t = {self.t_ns():g} ns · "
                              f"{fase}")  # fmt: skip
        self._mostrar_entradas()
        self.tempo_mudou.emit(self.t_ns())

    def ir(self, posicao: int) -> None:
        self.slider.setValue(max(0, min(self.slider.maximum(), posicao)))

    def passo(self, delta: int) -> None:
        self.ir(self.slider.value() + delta)

    def alternar(self) -> None:
        if self._relogio.isActive():
            self.pausar()
        else:
            if self.slider.value() >= self.slider.maximum():
                self.ir(0)
            self._relogio.start(self.velocidade.currentData())
            self.botoes["tocar"].setText("⏸")

    def pausar(self) -> None:
        self._relogio.stop()
        self.botoes["tocar"].setText("▶")

    def _ajustar_velocidade(self, _i: int) -> None:
        if self._relogio.isActive():
            self._relogio.start(self.velocidade.currentData())

    def _tique(self) -> None:
        if self.slider.value() >= self.slider.maximum():
            self.pausar()
            return
        self.passo(1)

    def definir_situacao(self, texto: str) -> None:
        self.situacao.setText(texto)
