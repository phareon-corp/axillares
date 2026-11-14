"""Janela principal: trilho de navegação à esquerda, telas à direita, sobre a trama."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from axillares import __version__
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core import recentes
from axillares.core.novo import criar_projeto
from axillares.core.projeto import ErroProjeto, carregar_projeto, encontrar_raiz
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import Ponto, Trama, botao, regua, rotulo
from axillares.gui.dialogos import DialogoNovoProjeto
from axillares.gui.espaco import (
    ABERTURA,
    COMPARAR,
    EDITOR,
    EXECUCOES,
    LAYOUT,
    PROJETO,
    AbaProjeto,
    AreaProjeto,
    BarraProjetos,
)
from axillares.gui.telas.abertura import TelaAbertura
from axillares.gui.tema import Espaco, Modo, Papel
from axillares.motor import Motor, obter_motor

ICONE = t.PASTA / "icones" / "axillares.svg"

# (número, nome, precisa de projeto aberto)
SECOES = (
    ("01", "Abertura", False),
    ("02", "Projeto", False),
    ("03", "Editor", True),
    ("04", "Execuções", True),
    ("05", "Layout", True),
    ("06", "Comparar", True),
)


class Trilho(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("trilho")
        self.setFixedWidth(Espaco.TRILHO)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, Espaco.L + 4, 0, Espaco.L)
        lay.setSpacing(0)

        marca = QHBoxLayout()
        marca.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        marca.setSpacing(6)
        marca.addWidget(Ponto(8, "acento", pulsar=True))
        self._nome_marca = rotulo("Axillares", Papel.MARCA)
        marca.addWidget(self._nome_marca)
        marca.addStretch(1)
        lay.addLayout(marca)
        sub = rotulo("Do Verilog ao GDSII", Papel.ROTULO, "3")
        self._expandidos: list[QWidget] = [self._nome_marca, sub]
        sub.setContentsMargins(Espaco.M + 2 + 30, 2, 0, 0)
        lay.addWidget(sub)
        lay.addSpacing(Espaco.XL)

        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self._precisam_projeto: list[QPushButton] = []
        for i, (numero, nome, precisa) in enumerate(SECOES):
            b = QPushButton(f"{numero}   {nome}")
            b.setProperty("rotulo_completo", f"{numero}   {nome}")
            b.setProperty("rotulo_curto", numero)
            b.setProperty("tipo", "nav")
            b.setFont(t.fonte(Papel.NAV))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if precisa:
                b.setEnabled(False)
                b.setToolTip("Abra ou crie um projeto primeiro.")
                self._precisam_projeto.append(b)
            self.grupo.addButton(b, i)
            lay.addWidget(b)
        self.grupo.button(0).setChecked(True)

        lay.addSpacing(Espaco.L)
        self.projeto = rotulo("", Papel.ROTULO, "3")
        self.projeto.setContentsMargins(Espaco.M + 2, 0, Espaco.M, 0)
        self.projeto.setWordWrap(True)
        lay.addWidget(self.projeto)
        breve = rotulo("07   Trilha · em breve", Papel.ROTULO, "3")
        self._expandidos += [self.projeto, breve]
        breve.setContentsMargins(Espaco.M + 2, Espaco.M, Espaco.M, 0)
        lay.addWidget(breve)

        lay.addStretch(1)
        caixa = QVBoxLayout()
        caixa.setContentsMargins(Espaco.M + 2, 0, Espaco.M + 2, 0)
        caixa.setSpacing(Espaco.S + 2)
        caixa.addWidget(rotulo("Tema", Papel.ROTULO, "3"))
        segmentos = QHBoxLayout()
        segmentos.setSpacing(0)
        self.modos = QButtonGroup(self)
        for i, (modo, texto) in enumerate(
            ((Modo.ESCURO, "Escuro"), (Modo.CLARO, "Claro"), (Modo.SISTEMA, "Sistema"))
        ):
            b = QPushButton(texto)
            b.setProperty("tipo", "segmento")
            b.setProperty("posicao", "inicio" if i == 0 else "fim" if i == 2 else "meio")
            b.setFont(t.fonte(Papel.ETIQUETA))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(t.tema().modo is modo)
            b.clicked.connect(lambda _c=False, m=modo: t.tema().aplicar(m))
            self.modos.addButton(b, i)
            segmentos.addWidget(b)
        caixa.addLayout(segmentos)
        t.tema().mudou.connect(self._sincronizar_modo)
        caixa.addSpacing(Espaco.M)
        caixa.addWidget(regua())
        caixa.addSpacing(Espaco.S)
        caixa.addWidget(rotulo(f"v {__version__} · Apache-2.0", Papel.ROTULO, "3"))
        lay.addLayout(caixa)
        self._caixa_tema = caixa

    def compactar(self, sim: bool) -> None:
        """Rail compacto (só os números): devolve espaço ao editor e ao layout."""
        self.setFixedWidth(64 if sim else Espaco.TRILHO)
        for w in self._expandidos:
            w.setVisible(not sim)
        for i in range(self._caixa_tema.count()):
            item = self._caixa_tema.itemAt(i)
            alvo = item.widget() or item.layout()
            if isinstance(alvo, QWidget):
                alvo.setVisible(not sim)
            elif alvo is not None:
                for j in range(alvo.count()):
                    w = alvo.itemAt(j).widget()
                    if w:
                        w.setVisible(not sim)
        for b in self.grupo.buttons():
            b.setText(b.property("rotulo_curto" if sim else "rotulo_completo"))
            b.setToolTip(b.property("rotulo_completo").split("   ")[-1] if sim else "")

    def _sincronizar_modo(self, _paleta: object) -> None:
        indice = (Modo.ESCURO, Modo.CLARO, Modo.SISTEMA).index(t.tema().modo)
        self.modos.button(indice).setChecked(True)

    def projeto_aberto(self, nome: str | None) -> None:
        for b in self._precisam_projeto:
            b.setEnabled(nome is not None)
            b.setToolTip("" if nome else "Abra ou crie um projeto primeiro.")
        self.projeto.setText(f"ABERTO: {nome}" if nome else "")


class FaixaAviso(QFrame):
    """Mensagem de erro passageira no rodapé — nunca um modal bloqueante."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("tipo", "faixa-progresso")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Espaco.MARGEM, Espaco.M - 2, Espaco.MARGEM, Espaco.M - 2)
        self.texto = rotulo("", Papel.CORPO)
        self.texto.setWordWrap(True)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(rotulo("✕", Papel.CORPO_FORTE, "falha"))
        lay.addWidget(self.texto, 1)
        fechar = botao("Fechar", "link")
        fechar.clicked.connect(self.hide)
        lay.addWidget(fechar)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def mostrar(self, mensagem: str) -> None:
        self.texto.setText(mensagem)
        self.show()
        self._timer.start(12_000)


class JanelaPrincipal(QMainWindow):
    """Trilho à esquerda; à direita, as abas dos projetos abertos e a tela corrente."""

    def __init__(
        self,
        perfil: Perfil | None = None,
        fabrica_executor: Callable[[], Executor] = ExecutorReal,
        verificar_ao_abrir: bool = True,
        fabrica_motor: Callable[[str], Motor] = obter_motor,
        projeto_inicial: Path | None = None,
        fabrica_editor: Callable[[], QWidget] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Axillares")
        self.setWindowIcon(QIcon(str(ICONE)))
        self.resize(1320, 860)
        self.setMinimumSize(900, 600)
        self._fabrica_motor = fabrica_motor
        self._fabrica_editor = fabrica_editor
        self.areas: list[AreaProjeto] = []
        self.ativa: AreaProjeto | None = None
        self.indice = ABERTURA
        self._pode_fechar = False
        self._tarefas: list[tarefas.Tarefa] = []

        raiz = Trama()
        raiz.setObjectName("raiz")
        lay = QHBoxLayout(raiz)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.trilho = Trilho()
        lay.addWidget(self.trilho)
        direita = QVBoxLayout()
        direita.setContentsMargins(0, 0, 0, 0)
        direita.setSpacing(0)
        self.barra = BarraProjetos()
        self.barra.novo.connect(self.novo_projeto)
        self.barra.abrir.connect(self.escolher_pasta)
        direita.addWidget(self.barra)
        self.pilha = QStackedWidget()
        direita.addWidget(self.pilha, 1)
        self.aviso = FaixaAviso()
        direita.addWidget(self.aviso)
        lay.addLayout(direita, 1)

        self.abertura = TelaAbertura(perfil or carregar_perfil(), fabrica_executor)
        self.pilha.addWidget(self.abertura)
        self.trilho.grupo.idClicked.connect(self.ir_para)
        self.abertura.botao_novo.clicked.connect(self.novo_projeto)
        self.abertura.botao_abrir.clicked.connect(self.escolher_pasta)
        self.abertura.abrir_projeto.connect(self.abrir_projeto)
        self.setCentralWidget(raiz)

        self.abertura.carregar_recentes()
        if verificar_ao_abrir:
            self.abertura.verificar()
        if projeto_inicial is not None:
            self.abrir_projeto(projeto_inicial)

    # --- atalhos para o projeto ativo (telas e testes) ----------------------------------------

    @property
    def sessao(self):
        return self.ativa.sessao if self.ativa else None

    @property
    def projeto(self):
        return self.ativa.projeto

    @property
    def editor(self):
        return self.ativa.editor

    @property
    def execucoes(self):
        return self.ativa.execucoes

    @property
    def layout_(self):
        return self.ativa.layout_

    @property
    def comparar(self):
        return self.ativa.comparar

    # --- abrir, criar, fechar projetos --------------------------------------------------------

    def _rodar(self, funcao, ao_concluir) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(self.aviso.mostrar)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    def area_de(self, raiz: Path) -> AreaProjeto | None:
        raiz = Path(raiz).resolve()
        return next((a for a in self.areas if a.raiz == raiz), None)

    def abrir_projeto(self, pasta: Path) -> None:
        """Abre numa aba nova; se já estiver aberto, só muda para a aba dele."""
        try:
            raiz = encontrar_raiz(Path(pasta))
        except ErroProjeto as erro:
            self.aviso.mostrar(str(erro))
            return
        existente = self.area_de(raiz)
        if existente is not None:
            self.ativar(existente)
            return

        def carregar():
            projeto = carregar_projeto(raiz)
            recentes.registrar(projeto.raiz, projeto.nome)
            return projeto

        self._rodar(carregar, self._adicionar)

    def criar_projeto(self, nome, destino, modelo="vazio", pdk="skywater130", frequencia_mhz=100.0):
        def criar():
            projeto = carregar_projeto(
                criar_projeto(nome, Path(destino), modelo, pdk, frequencia_mhz)
            )
            recentes.registrar(projeto.raiz, projeto.nome)
            return projeto

        self._rodar(criar, self._adicionar)

    def novo_projeto(self) -> None:
        dialogo = DialogoNovoProjeto(self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.criar_projeto(**_args_criacao(dialogo.escolhas()))

    def escolher_pasta(self) -> None:
        inicio = str(self.ativa.raiz.parent) if self.ativa else str(Path.home())
        pasta = QFileDialog.getExistingDirectory(
            self, "Abrir projeto (pasta com axil.toml)", inicio
        )
        if pasta:
            self.abrir_projeto(Path(pasta))

    def _fontes(self) -> list:
        return [(a.nome, a.sessao.caderno) for a in self.areas if a.sessao.caderno]

    def _adicionar(self, projeto) -> None:
        existente = self.area_de(projeto.raiz)
        if existente is not None:
            self.ativar(existente)
            return
        area = AreaProjeto(projeto, self._fabrica_motor, self._fabrica_editor, self._fontes)
        area.sessao.erro.connect(self.aviso.mostrar)
        area.sessao.pedir_tela.connect(lambda nome, arg, a=area: self._pedido_de_tela(a, nome, arg))
        area.sessao.execucoes_mudaram.connect(self._execucoes_mudaram)
        area.execucoes.lista.comparar.connect(lambda x, y, a=area: self._comparar(a, x, y))
        self.areas.append(area)
        self.pilha.addWidget(area)
        aba = AbaProjeto(area)
        aba.clicada.connect(self.ativar)
        aba.fechar.connect(self.fechar_projeto)
        self.barra.adicionar(aba)
        # a área nova entrou na lista de fontes: todos os layouts passam a enxergá-la
        for a in self.areas:
            a.layout_._recarregar_se_visivel()
        self.ativar(area, PROJETO)

    def _execucoes_mudaram(self) -> None:
        # um layout pode estar mostrando execuções de outro projeto
        for a in self.areas:
            a.layout_._recarregar_se_visivel()

    def ativar(self, area: AreaProjeto, indice: int | None = None) -> None:
        self.ativa = area
        self.barra.ativar(area)
        self.trilho.projeto_aberto(area.nome)
        self.setWindowTitle(f"{area.nome} — Axillares")
        self.ir_para(indice or area.indice)

    def fechar_projeto(self, area: AreaProjeto) -> bool:
        """Fecha uma aba de projeto. Pergunta antes de perder trabalho. True se fechou."""
        if area.executando:
            r = QMessageBox.question(
                self, "Execução em andamento",
                f"{area.nome} está executando. Interromper e fechar o projeto?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )  # fmt: skip
            if r != QMessageBox.StandardButton.Yes:
                return False
        if area.tem_alteracoes:
            r = QMessageBox.question(
                self, "Alterações não salvas",
                f"Há arquivos de {area.nome} com alterações não salvas. Salvar antes de fechar?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )  # fmt: skip
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Save:
                area.editor._salvar_e_seguir(lambda a=area: self._remover(a))
                return True
        self._remover(area)
        return True

    def _remover(self, area: AreaProjeto) -> None:
        if area not in self.areas:
            return
        area.encerrar()
        aba = next(a for a in self.barra.abas if a.area is area)
        self.barra.remover(aba)
        self.areas.remove(area)
        self.pilha.removeWidget(area)
        area.deleteLater()
        if self.ativa is area:
            self.ativa = None
            if self.areas:
                self.ativar(self.areas[-1])
            else:
                self.trilho.projeto_aberto(None)
                self.setWindowTitle("Axillares")
                self.barra.ativar(None)
                self.ir_para(ABERTURA)
        for a in self.areas:
            a.layout_._recarregar_se_visivel()

    # --- navegação ----------------------------------------------------------------------------

    def ir_para(self, indice: int) -> None:
        if indice != ABERTURA and self.ativa is None:
            indice = ABERTURA
        self.indice = indice
        self._ajustar_trilho()
        self.trilho.grupo.button(indice).setChecked(True)
        if indice == ABERTURA:
            self.pilha.setCurrentWidget(self.abertura)
            self.abertura.carregar_recentes()
            return
        self.ativa.ir_para(indice)
        self.pilha.setCurrentWidget(self.ativa)

    def _ajustar_trilho(self) -> None:
        # Editor e Layout precisam de largura; em janelas estreitas, todas as telas também
        self.trilho.compactar(self.indice in (EDITOR, LAYOUT) or self.width() < 1180)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_trilho()

    def tela_atual(self) -> int:
        return self.indice

    def abrir_no_editor(self, caminho: Path, linha: int = 0, coluna: int = 1) -> None:
        self.ir_para(EDITOR)
        self.editor.abrir(caminho, linha, coluna)

    def _comparar(self, area: AreaProjeto, a: str, b: str) -> None:
        area.comparar.pedir(a, b)
        self.ativar(area, COMPARAR)

    def _pedido_de_tela(self, area: AreaProjeto, nome: str, argumento: object) -> None:
        if nome == "criar-projeto":
            self.criar_projeto(**_args_criacao(argumento))
            return
        if nome == "abrir-projeto":
            self.abrir_projeto(Path(argumento))
            return
        self.ativar(area)
        if nome == "execucao":
            area.execucoes.abrir(str(argumento))
            self.ir_para(EXECUCOES)
        elif nome == "como-funciona":
            self.ir_para(PROJETO)
            area.projeto.mostrar_fluxo()
        elif nome == "layout":
            area.layout_.mostrar_execucao(str(argumento))
            self.ir_para(LAYOUT)

    def closeEvent(self, evento: QCloseEvent) -> None:
        if not self._pode_fechar:
            pendentes = [a for a in self.areas if a.tem_alteracoes or a.executando]
            for area in pendentes:
                self.ativar(area)
                if not self.fechar_projeto(area):
                    evento.ignore()
                    return
        self.abertura.encerrar()
        for area in list(self.areas):
            area.encerrar()
        tarefas.esperar_todas()
        super().closeEvent(evento)


def _args_criacao(escolhas: dict) -> dict:
    return {
        "nome": escolhas["nome"],
        "destino": escolhas["destino"],
        "modelo": escolhas["modelo"],
        "pdk": escolhas["pdk"],
        "frequencia_mhz": escolhas["frequencia_mhz"],
    }


__all__ = ["JanelaPrincipal"]
