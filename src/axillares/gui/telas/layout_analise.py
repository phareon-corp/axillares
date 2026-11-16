"""Peças do painel lateral do Layout: classes de máscaras, destaques de dispositivos e ponteiras.

- Classes: grupos de camadas com nome e cor (core/classes_camadas.py). Um clique liga ou desliga a
  classe inteira; duplo clique mostra só ela; ✎ edita; × remove. "Gerar" refaz a partir do layout.
- Destaques: transistores PMOS/NMOS, poço N, diodos, taps, contatos — achados pelo KLayout, com
  quantos de cada há no desenho.
- Ponteiras: cada clique no modo Ponteira segue o nó elétrico daquele ponto (KLayout) e mostra o
  nome, as camadas por onde passa e os pinos das células ligadas a ele.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from axillares.core import formato as fmt
from axillares.core.classes_camadas import Classe
from axillares.gui import tema as t
from axillares.gui.componentes import botao, repolir, rotulo
from axillares.gui.tema import Espaco, Papel

EXPLICA_DESTAQUE = {
    "pmos": "Onde o poly cruza a difusão dentro do poço N: um transistor de canal P. "
    "Liga a saída ao VDD quando a porta está em 0.",
    "nmos": "Onde o poly cruza a difusão fora do poço N: um transistor de canal N. "
    "Liga a saída ao terra quando a porta está em 1.",
    "poco_n": "A região dopada tipo N onde moram os transistores PMOS. Fica ligada ao VDD "
    "pelos taps.",
    "diodo": "Diodos do PDK (marcador areaid.diode): protegem as entradas contra carga "
    "acumulada durante a fabricação (efeito antena).",
    "tap": "Contatos que prendem o poço N ao VDD e o substrato ao terra — sem eles o circuito "
    "pode travar (latch-up).",
    "contato": "Os furos (licon) que ligam difusão e poly ao primeiro nível de fio (li1).",
}
ORDEM_DESTAQUES = ("pmos", "nmos", "poco_n", "diodo", "tap", "contato")
NOMES_CAMADA_CONDUTORA = {
    "sd": "difusão (fonte/dreno)", "porta": "poly (porta)", "66/44": "licon", "67/20": "li1",
    "67/44": "mcon", "68/20": "met1", "68/44": "via", "69/20": "met2", "69/44": "via2",
    "70/20": "met3", "70/44": "via3", "71/20": "met4", "71/44": "via4", "72/20": "met5",
}  # fmt: skip


class Amostra(QWidget):
    """Quadradinho de cor."""

    def __init__(self, cor: str, tamanho: int = 12) -> None:
        super().__init__()
        self.cor = cor
        self.setFixedSize(tamanho, tamanho)

    def definir(self, cor: str) -> None:
        self.cor = cor
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(t.paleta().qcolor("linha_forte"))
        p.setBrush(QColor(self.cor))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)


# --- classes ------------------------------------------------------------------------------------


class LinhaClasse(QFrame):
    alternada = Signal(int, bool)
    isolada = Signal(int)
    editar = Signal(int)
    remover = Signal(int)

    def __init__(self, i: int, classe: Classe, visivel: bool) -> None:
        super().__init__()
        self.i = i
        self.visivel = visivel
        self.setProperty("tipo", "linha-classe")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 2, 4)
        lay.setSpacing(Espaco.S)
        self.amostra = Amostra(classe.cor, 14)
        lay.addWidget(self.amostra)
        coluna = QVBoxLayout()
        coluna.setSpacing(0)
        self.nome = rotulo(classe.nome, Papel.PEQUENO)
        coluna.addWidget(self.nome)
        n = len(classe.camadas)
        coluna.addWidget(rotulo(f"{n} camada{'s' if n != 1 else ''}", Papel.ROTULO, "3"))
        lay.addLayout(coluna, 1)
        for texto, dica, sinal in (("✎", "Editar a classe", self.editar),
                                   ("×", "Remover a classe", self.remover)):  # fmt: skip
            b = QPushButton(texto)
            b.setProperty("tipo", "fechar-aba")
            b.setFixedSize(22, 22)
            b.setToolTip(dica)
            b.clicked.connect(lambda _c=False, s=sinal: s.emit(self.i))
            lay.addWidget(b)
        self.setToolTip("clique: liga/desliga · duplo clique: só esta classe")
        self.definir(visivel)

    def definir(self, visivel: bool) -> None:
        self.visivel = visivel
        self.setProperty("apagada", "nao" if visivel else "sim")
        self.nome.setProperty("tom", None if visivel else "3")
        repolir(self)
        repolir(self.nome)

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.alternada.emit(self.i, not self.visivel)

    def mouseDoubleClickEvent(self, _evento: QMouseEvent) -> None:
        self.isolada.emit(self.i)


class DialogoClasse(QDialog):
    """Criar ou editar uma classe: nome, cor e quais camadas entram."""

    def __init__(self, camadas: list[tuple[str, str, str]], classe: Classe | None = None,
                 pai: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(pai)
        self.setWindowTitle("Classe de máscaras")
        self.setMinimumWidth(420)
        self._cor = classe.cor if classe else (camadas[0][2] if camadas else t.paleta().acento)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.L, Espaco.L, Espaco.L, Espaco.M)
        lay.setSpacing(Espaco.S + 2)
        lay.addWidget(rotulo("Classe de máscaras", Papel.ROTULO, "3"))
        lay.addWidget(rotulo("Editar classe" if classe else "Nova classe", Papel.TITULO))
        linha = QHBoxLayout()
        self.nome = QLineEdit(classe.nome if classe else "")
        self.nome.setPlaceholderText("por exemplo: Transistores")
        self.nome.setFont(t.fonte(Papel.CORPO))
        self.nome.textChanged.connect(self._validar)
        linha.addWidget(self.nome, 1)
        self.amostra = Amostra(self._cor, 22)
        linha.addWidget(self.amostra)
        cor = botao("Cor…", "compacto")
        cor.clicked.connect(self._escolher_cor)
        linha.addWidget(cor)
        lay.addLayout(linha)
        lay.addWidget(rotulo("Camadas", Papel.ROTULO, "3"))
        self.lista = QListWidget()
        self.lista.setFont(t.fonte(Papel.MONO))
        marcadas = set(classe.camadas) if classe else set()
        for nome, fonte, _cor in camadas:
            item = QListWidgetItem(f"{nome.split(' - ')[0]}   {fonte}")
            item.setData(Qt.ItemDataRole.UserRole, fonte)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if fonte in marcadas
                               else Qt.CheckState.Unchecked)  # fmt: skip
            self.lista.addItem(item)
        self.lista.itemChanged.connect(lambda _i: self._validar())
        lay.addWidget(self.lista, 1)
        self.aviso = rotulo("", Papel.PEQUENO, "falha")
        lay.addWidget(self.aviso)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = botao("Cancelar", "fantasma")
        cancelar.clicked.connect(self.reject)
        self.ok = botao("Salvar classe", "primario")
        self.ok.clicked.connect(self.accept)
        acoes.addWidget(cancelar)
        acoes.addWidget(self.ok)
        lay.addLayout(acoes)
        self._validar()

    def _escolher_cor(self) -> None:
        cor = QColorDialog.getColor(QColor(self._cor), self, "Cor da classe")
        if cor.isValid():
            self._cor = cor.name().upper()
            self.amostra.definir(self._cor)

    def marcadas(self) -> list[str]:
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.CheckState.Checked]  # fmt: skip

    def _validar(self) -> None:
        problema = ""
        if not self.nome.text().strip():
            problema = "Dê um nome à classe."
        elif not self.marcadas():
            problema = "Marque pelo menos uma camada."
        self.aviso.setText(problema)
        self.ok.setEnabled(not problema)

    def classe(self) -> Classe:
        return Classe(nome=self.nome.text().strip(), cor=self._cor, camadas=self.marcadas())


# --- análise: destaques e ponteiras ------------------------------------------------------------


class PainelAnalise(QWidget):
    destaques_mudaram = Signal(object)
    """set[str] dos destaques ligados."""
    remover_sonda = Signal(int)
    limpar_sondas = Signal()
    ver_onda = Signal(str)
    """Nome do nó, para abrir o sinal correspondente na onda."""

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, Espaco.S, 0, 0)
        lay.setSpacing(Espaco.S)
        lay.addWidget(rotulo("Destaques", Papel.ROTULO, "3"))
        dica = rotulo("O resto do desenho esmaece; os componentes ficam por cima, em cor viva.",
                      Papel.PEQUENO, "2")  # fmt: skip
        dica.setWordWrap(True)
        lay.addWidget(dica)
        self.caixas: dict[str, QCheckBox] = {}
        self.amostras: dict[str, Amostra] = {}
        self.contagens: dict[str, object] = {}
        for chave in ORDEM_DESTAQUES:
            linha = QHBoxLayout()
            linha.setSpacing(Espaco.S)
            amostra = Amostra(t.paleta().tinta_3)
            caixa = QCheckBox(chave)
            caixa.setFont(t.fonte(Papel.PEQUENO))
            caixa.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            caixa.setToolTip(EXPLICA_DESTAQUE[chave])
            caixa.toggled.connect(self._mudou)
            quantos = rotulo("", Papel.MONO, "3")
            linha.addWidget(amostra)
            linha.addWidget(caixa, 1)
            linha.addWidget(quantos)
            lay.addLayout(linha)
            self.caixas[chave], self.amostras[chave], self.contagens[chave] = (
                caixa,
                amostra,
                quantos,
            )
        self.explicacao = rotulo("", Papel.PEQUENO, "2")
        self.explicacao.setWordWrap(True)
        lay.addWidget(self.explicacao)

        topo = QHBoxLayout()
        topo.addWidget(rotulo("Ponteiras", Papel.ROTULO, "3"), 1)
        limpar = botao("Limpar", "link")
        limpar.setFont(t.fonte(Papel.ETIQUETA))
        limpar.clicked.connect(self.limpar_sondas)
        topo.addWidget(limpar)
        lay.addSpacing(Espaco.S)
        lay.addLayout(topo)
        self.dica_sonda = rotulo(
            "Escolha “Ponteira” na barra e clique num fio: o KLayout segue o nó elétrico — o "
            "nome, por onde ele passa e que pinos de célula ele liga.", Papel.PEQUENO, "2",
        )  # fmt: skip
        self.dica_sonda.setWordWrap(True)
        lay.addWidget(self.dica_sonda)
        self._lay_sondas = QVBoxLayout()
        self._lay_sondas.setSpacing(Espaco.S)
        lay.addLayout(self._lay_sondas)
        lay.addStretch(1)
        self.indisponivel = rotulo("", Papel.PEQUENO, "aviso")
        self.indisponivel.setWordWrap(True)
        self.indisponivel.hide()
        lay.addWidget(self.indisponivel)

    def _mudou(self, _ligado: bool) -> None:
        ativos = {c for c, caixa in self.caixas.items() if caixa.isChecked()}
        ultimo = next((c for c in ORDEM_DESTAQUES if c in ativos), None)
        self.explicacao.setText(EXPLICA_DESTAQUE[ultimo] if ultimo else "")
        self.destaques_mudaram.emit(ativos)

    def definir_disponivel(self, disponivel: bool) -> None:
        for caixa in self.caixas.values():
            caixa.setEnabled(disponivel)
        self.indisponivel.setVisible(not disponivel)
        self.indisponivel.setText(
            ""
            if disponivel
            else "Destaques e ponteiras precisam das regras do PDK; por ora só o sky130 as tem."
        )

    def definir_estado(self, ativos: set[str], contagem: dict) -> None:
        for chave, caixa in self.caixas.items():
            caixa.blockSignals(True)
            caixa.setChecked(chave in ativos)
            caixa.blockSignals(False)
            dados = contagem.get(chave)
            if dados:
                caixa.setText(dados["titulo"])
                self.amostras[chave].definir(dados["cor"])
                self.contagens[chave].setText(fmt.numero(dados["quantos"], 0))

    def definir_sondas(self, sondas: dict[int, dict], cores: dict[int, str],
                       sinais_na_onda: set[str]) -> None:  # fmt: skip
        while self._lay_sondas.count():
            item = self._lay_sondas.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.dica_sonda.setVisible(not sondas)
        for n, dados in sorted(sondas.items()):
            self._lay_sondas.addWidget(self._cartao(n, dados, cores[n], sinais_na_onda))

    def _cartao(self, n: int, dados: dict, cor: str, sinais_na_onda: set[str]) -> QFrame:
        cartao = QFrame()
        cartao.setProperty("tipo", "cartao-sonda")
        c = QVBoxLayout(cartao)
        c.setContentsMargins(Espaco.S + 2, Espaco.S, Espaco.S, Espaco.S)
        c.setSpacing(3)
        topo = QHBoxLayout()
        topo.setSpacing(Espaco.S)
        topo.addWidget(Amostra(cor, 12))
        no = dados.get("no")
        titulo = no if no else "sem condutor aqui"
        nome = rotulo(f"P{n}  {titulo}", Papel.CORPO_FORTE)
        nome.setWordWrap(True)
        topo.addWidget(nome, 1)
        fechar = QPushButton("×")
        fechar.setProperty("tipo", "fechar-aba")
        fechar.setFixedSize(20, 20)
        fechar.clicked.connect(lambda: self.remover_sonda.emit(n))
        topo.addWidget(fechar)
        c.addLayout(topo)
        if no:
            dentro = dados.get("dentro")
            if dentro:
                celula = dentro["celula"].split("__")[-1]
                tipo = f"nó dentro da célula {celula}, entre os transistores dela"
            elif dados.get("interno"):
                tipo = "nó interno do circuito (o nome é da ferramenta)"
            elif no in {"VDD", "VSS", "VPWR", "VGND"}:
                tipo = "alimentação"
            else:
                tipo = "sinal com nome"
            r_tipo = rotulo(tipo, Papel.ROTULO, "3")
            r_tipo.setWordWrap(True)
            c.addWidget(r_tipo)
            camadas = [NOMES_CAMADA_CONDUTORA.get(k, k) for k in dados.get("camadas", {})]
            if camadas:
                r = rotulo("passa por: " + ", ".join(camadas), Papel.PEQUENO, "2")
                r.setWordWrap(True)
                c.addWidget(r)
            pinos = dados.get("pinos", [])
            if pinos:
                texto = ", ".join(f"{p['celula'].split('__')[-1]}.{p['pino']}" for p in pinos[:8])
                r = rotulo(f"liga: {texto}{' …' if len(pinos) > 8 else ''}", Papel.PEQUENO, "2")
                r.setWordWrap(True)
                c.addWidget(r)
            base = no.split("[")[0]
            if base in sinais_na_onda:
                ver = botao(f"Ver {no} na onda →", "link")
                ver.setFont(t.fonte(Papel.ETIQUETA))
                ver.clicked.connect(lambda: self.ver_onda.emit(no))
                c.addWidget(ver, 0, Qt.AlignmentFlag.AlignLeft)
        disp = dados.get("dispositivo")
        if disp:
            tipo_t = "PMOS" if disp["tipo"] == "pmos" else "NMOS"
            medidas = f"{fmt.numero(disp['largura'], 2)} × {fmt.numero(disp['altura'], 2)} µm"
            texto_disp = f"sobre a porta de um transistor {tipo_t} · {medidas}"
            r_disp = rotulo(texto_disp, Papel.PEQUENO, "acento")
            r_disp.setWordWrap(True)
            c.addWidget(r_disp)
        return cartao
