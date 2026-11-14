"""Diálogo de projeto novo: escolher o modelo, o nome, a pasta, o PDK e o relógio."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from axillares.core.novo import Modelo, modelos
from axillares.gui import tema as t
from axillares.gui.componentes import botao, repolir, rotulo
from axillares.gui.tema import Espaco, Papel

PDKS = (
    ("skywater130", "SkyWater 130 nm", "testado"),
    ("gf180", "GlobalFoundries 180 nm", "experimental"),
    ("ihp130", "IHP 130 nm", "experimental"),
)
_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


def _ocupada(pasta: Path) -> bool:
    return pasta.exists() and (not pasta.is_dir() or any(pasta.iterdir()))


def nome_livre(destino: Path, base: str) -> str:
    """meu-chip, meu-chip-2, meu-chip-3… o primeiro que não colide com uma pasta com conteúdo."""
    if not _ocupada(destino / base):
        return base
    n = 2
    while _ocupada(destino / f"{base}-{n}"):
        n += 1
    return f"{base}-{n}"


class _Responsivo(QWidget):
    """Avisa a própria largura a cada redimensionamento."""

    def __init__(self, ao_mudar) -> None:
        super().__init__()
        self._ao_mudar = ao_mudar

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ao_mudar(self.width())


class CartaoModelo(QFrame):
    escolhido = Signal(str)

    def __init__(self, m: Modelo, numero: int) -> None:
        super().__init__()
        self.modelo = m
        self.setProperty("tipo", "cartao-modelo")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.M + 2, Espaco.M, Espaco.M + 2, Espaco.M)
        lay.setSpacing(6)
        topo = QHBoxLayout()
        topo.addWidget(rotulo(f"{numero:02d} /", Papel.NUMERO_SECAO, "acento"))
        topo.addWidget(rotulo(m.nivel, Papel.ROTULO, "3"))
        topo.addStretch(1)
        lay.addLayout(topo)
        titulo = rotulo(m.titulo, Papel.TITULO)
        titulo.setWordWrap(True)
        lay.addWidget(titulo)
        desc = rotulo(m.descricao, Papel.PEQUENO, "2")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        if m.aprende:
            aprende = rotulo("aprende: " + " · ".join(m.aprende), Papel.ROTULO, "3")
            aprende.setWordWrap(True)
            lay.addWidget(aprende)
        lay.addStretch(1)

    def marcar(self, sim: bool) -> None:
        self.setProperty("escolhido", "sim" if sim else "nao")
        repolir(self)

    def mouseReleaseEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self.escolhido.emit(self.modelo.id)


class DialogoNovoProjeto(QDialog):
    def __init__(self, pai: QWidget | None = None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Novo projeto")
        self.setMinimumWidth(640)
        tela = QGuiApplication.primaryScreen()
        disponivel = tela.availableGeometry() if tela else None
        if disponivel is not None:
            self.resize(min(900, int(disponivel.width() * 0.9)),
                        min(860, int(disponivel.height() * 0.9)))  # fmt: skip
        self.modelo_id = "vazio"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.XL, Espaco.XL, Espaco.XL, Espaco.L)
        lay.setSpacing(Espaco.M)
        lay.addWidget(rotulo("Novo projeto", Papel.ROTULO, "3"))
        titulo = rotulo(f"Por onde {t.serifa('começar', tamanho_px=30)}?", Papel.TITULO, rico=True)
        lay.addWidget(titulo)
        lay.addSpacing(Espaco.S)

        # os cartões rolam se a tela for baixa; nada é espremido
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        miolo = _Responsivo(self._reorganizar)
        grade = QGridLayout(miolo)
        self._grade = grade
        self._colunas = 2
        grade.setContentsMargins(0, 0, 4, 0)
        grade.setSpacing(Espaco.S + 2)
        self.cartoes: dict[str, CartaoModelo] = {}
        for i, m in enumerate(modelos()):
            c = CartaoModelo(m, i + 1)
            c.escolhido.connect(self._escolher)
            grade.addWidget(c, i // 2, i % 2)
            self.cartoes[m.id] = c
        area.setWidget(miolo)
        lay.addWidget(area, 1)
        lay.addSpacing(Espaco.S)

        campos = QGridLayout()
        campos.setHorizontalSpacing(Espaco.M)
        campos.setVerticalSpacing(6)
        campos.addWidget(rotulo("Nome", Papel.ROTULO, "3"), 0, 0)
        campos.addWidget(rotulo("Criar dentro de", Papel.ROTULO, "3"), 0, 1)
        self.nome = QLineEdit(nome_livre(Path.home() / "Projetos", "meu-chip"))
        self.nome.setFont(t.fonte(Papel.CORPO))
        self.nome.textChanged.connect(self._validar)
        campos.addWidget(self.nome, 1, 0)
        pasta = QHBoxLayout()
        self.destino = QLineEdit(str(Path.home() / "Projetos"))
        self.destino.setFont(t.fonte(Papel.MONO))
        self.destino.textChanged.connect(self._validar)
        escolher = botao("Escolher…", "compacto")
        escolher.clicked.connect(self._escolher_pasta)
        pasta.addWidget(self.destino, 1)
        pasta.addWidget(escolher)
        campos.addLayout(pasta, 1, 1)
        campos.addWidget(rotulo("PDK (o processo de fabricação)", Papel.ROTULO, "3"), 2, 0)
        campos.addWidget(rotulo("Relógio alvo", Papel.ROTULO, "3"), 2, 1)
        self.pdk = QComboBox()
        self.pdk.setFont(t.fonte(Papel.CORPO))
        for valor, nome, situacao in PDKS:
            self.pdk.addItem(f"{nome} — {situacao}", valor)
        campos.addWidget(self.pdk, 3, 0)
        self.frequencia = QDoubleSpinBox()
        self.frequencia.setFont(t.fonte(Papel.MONO))
        self.frequencia.setRange(1, 1000)
        self.frequencia.setDecimals(0)
        self.frequencia.setValue(100)
        self.frequencia.setSuffix(" MHz")
        campos.addWidget(self.frequencia, 3, 1)
        campos.setColumnStretch(0, 1)
        campos.setColumnStretch(1, 1)
        lay.addLayout(campos)

        self.aviso = rotulo("", Papel.PEQUENO, "falha")
        self.aviso.setWordWrap(True)
        lay.addWidget(self.aviso)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = botao("Cancelar", "fantasma")
        cancelar.clicked.connect(self.reject)
        self.criar = botao("Criar projeto", "primario")
        self.criar.setDefault(True)
        self.criar.clicked.connect(self.accept)
        acoes.addWidget(cancelar)
        acoes.addWidget(self.criar)
        lay.addLayout(acoes)
        self._escolher("vazio")
        self._validar()

    def _reorganizar(self, largura: int) -> None:
        """Duas colunas de cartões quando cabe; uma só em telas estreitas."""
        colunas = 2 if largura >= 620 else 1
        if colunas == self._colunas:
            return
        self._colunas = colunas
        for i, c in enumerate(self.cartoes.values()):
            self._grade.removeWidget(c)
            self._grade.addWidget(c, i // colunas, i % colunas)

    def _escolher(self, ident: str) -> None:
        self.modelo_id = ident
        for i, c in self.cartoes.items():
            c.marcar(i == ident)

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Criar dentro de", self.destino.text())
        if pasta:
            self.destino.setText(pasta)

    def _validar(self) -> None:
        """Erros aparecem aqui, antes de criar — nunca depois que o diálogo fechou."""
        nome = self.nome.text().strip()
        destino = Path(self.destino.text().strip()).expanduser()
        problema = ""
        if not _NOME.match(nome):
            problema = "Use letras, números, _ ou -, começando por letra."
        elif _ocupada(destino / nome):
            livre = nome_livre(destino, nome)
            problema = f"Já existe uma pasta “{nome}” em {destino}. Que tal “{livre}”?"
        elif destino.exists() and not destino.is_dir():
            problema = f"{destino} não é uma pasta."
        self.aviso.setText(problema)
        self.nome.setProperty("erro", "sim" if problema else "nao")
        repolir(self.nome)
        self.criar.setEnabled(not problema)

    def escolhas(self) -> dict:
        return {
            "nome": self.nome.text().strip(),
            "destino": Path(self.destino.text()).expanduser(),
            "modelo": self.modelo_id,
            "pdk": self.pdk.currentData(),
            "frequencia_mhz": float(self.frequencia.value()),
        }


_MODULO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LINGUAGENS_NOVO = (("SystemVerilog  (.sv)", ".sv"), ("Verilog  (.v)", ".v"))


def _pasta_dos_padroes(padroes: list[str], padrao: str) -> str:
    """'rtl/**/*.v' → 'rtl'. Sem padrão com pasta fixa, usa o nome de costume."""
    for p in padroes:
        primeira = p.split("/")[0]
        if "/" in p and not any(c in primeira for c in "*?["):
            return primeira
    return padrao


class DialogoNovoArquivo(QDialog):
    """Nome do módulo, linguagem, papel (circuito ou testbench) e pasta — com o caminho final à
    vista e validação ao digitar."""

    def __init__(self, projeto, pai: QWidget | None = None) -> None:
        super().__init__(pai)
        self.projeto = projeto
        self.setWindowTitle("Novo arquivo")
        self.setMinimumWidth(520)
        self._pasta_editada = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Espaco.XL, Espaco.XL, Espaco.XL, Espaco.L)
        lay.setSpacing(Espaco.M)
        lay.addWidget(rotulo("Novo arquivo", Papel.ROTULO, "3"))
        lay.addWidget(
            rotulo(f"Um {t.serifa('módulo', tamanho_px=30)} novo", Papel.TITULO, rico=True)
        )
        explicacao = rotulo(
            "Cada arquivo guarda um módulo, com o mesmo nome do arquivo. O esqueleto já vem com "
            "relógio, reset e um registrador — troque pelo seu circuito.",
            Papel.PEQUENO,
            "2",
        )
        explicacao.setWordWrap(True)
        lay.addWidget(explicacao)

        campos = QGridLayout()
        campos.setHorizontalSpacing(Espaco.M)
        campos.setVerticalSpacing(6)
        campos.addWidget(rotulo("Nome do módulo", Papel.ROTULO, "3"), 0, 0)
        campos.addWidget(rotulo("Linguagem", Papel.ROTULO, "3"), 0, 1)
        self.nome = QLineEdit("")
        self.nome.setPlaceholderText("somador")
        self.nome.setFont(t.fonte(Papel.MONO))
        self.nome.textChanged.connect(self._validar)
        campos.addWidget(self.nome, 1, 0)
        self.linguagem = QComboBox()
        self.linguagem.setFont(t.fonte(Papel.CORPO))
        for rotulo_, ext in LINGUAGENS_NOVO:
            self.linguagem.addItem(rotulo_, ext)
        self.linguagem.currentIndexChanged.connect(self._validar)
        campos.addWidget(self.linguagem, 1, 1)
        campos.addWidget(rotulo("Papel", Papel.ROTULO, "3"), 2, 0)
        campos.addWidget(rotulo("Pasta", Papel.ROTULO, "3"), 2, 1)
        self.tipo = QComboBox()
        self.tipo.setFont(t.fonte(Papel.CORPO))
        self.tipo.addItem("Módulo — o circuito", "modulo")
        self.tipo.addItem("Testbench — simulação", "testbench")
        self.tipo.currentIndexChanged.connect(self._tipo_mudou)
        campos.addWidget(self.tipo, 3, 0)
        self.pasta = QLineEdit(self._pasta_padrao())
        self.pasta.setFont(t.fonte(Papel.MONO))
        self.pasta.textEdited.connect(self._pasta_mudou)
        campos.addWidget(self.pasta, 3, 1)
        campos.setColumnStretch(0, 1)
        campos.setColumnStretch(1, 1)
        lay.addLayout(campos)

        self.previa = rotulo("", Papel.MONO, "2")
        lay.addWidget(self.previa)
        self.aviso = rotulo("", Papel.PEQUENO, "falha")
        self.aviso.setWordWrap(True)
        lay.addWidget(self.aviso)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        cancelar = botao("Cancelar", "fantasma")
        cancelar.clicked.connect(self.reject)
        self.criar = botao("Criar arquivo", "primario")
        self.criar.setDefault(True)
        self.criar.clicked.connect(self.accept)
        acoes.addWidget(cancelar)
        acoes.addWidget(self.criar)
        lay.addLayout(acoes)
        self._validar()

    def _pasta_padrao(self) -> str:
        fontes = self.projeto.fontes
        if self.tipo.currentData() == "testbench":
            return _pasta_dos_padroes(fontes.testbenches, "tb")
        return _pasta_dos_padroes(fontes.rtl, "rtl")

    def _tipo_mudou(self) -> None:
        if not self._pasta_editada:
            self.pasta.setText(self._pasta_padrao())
        self._validar()

    def _pasta_mudou(self) -> None:
        self._pasta_editada = True
        self._validar()

    @property
    def relativo(self) -> str:
        pasta = self.pasta.text().strip().strip("/")
        nome = self.nome.text().strip() + (self.linguagem.currentData() or ".sv")
        return f"{pasta}/{nome}" if pasta else nome

    def _validar(self) -> None:
        nome = self.nome.text().strip()
        problema = ""
        if nome and not _MODULO.match(nome):
            problema = "Use letras, números e _, começando por letra (é o nome do módulo)."
        elif ".." in Path(self.pasta.text().strip()).parts:
            problema = "A pasta precisa ficar dentro do projeto."
        elif nome and (self.projeto.raiz / self.relativo).exists():
            problema = f"{self.relativo} já existe."
        self.previa.setText(f"→ {self.relativo}" if nome else "")
        self.aviso.setText(problema)
        self.nome.setProperty("erro", "sim" if problema else "nao")
        repolir(self.nome)
        self.criar.setEnabled(bool(nome) and not problema)

    def escolhas(self) -> dict:
        return {"relativo": self.relativo, "tipo": self.tipo.currentData()}
