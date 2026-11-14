"""Assistente do editor: as ajudas que dependem de ferramentas da imagem.

- Servidor de linguagem (Verible): erros de sintaxe ao digitar, formatar, ir à definição,
  referências, renomear e a estrutura do arquivo.
- Lint (Verilator): confere o projeto inteiro depois de salvar, com avisos explicados.

Tudo roda fora da thread da interface. Respostas e avisos chegam por sinais, já na thread da
interface. Sem contêiner ou sem a imagem, o editor continua funcionando — só sem essas ajudas.

`AXIL_SEM_ASSISTENTE=1` desliga tudo (os testes da interface usam, para não subir contêineres).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from axillares.core.modelos import Local
from axillares.core.projeto import Projeto
from axillares.gui import tarefas

EXTENSOES_HDL = {".v", ".sv", ".vh", ".svh"}
ESPERA_LINT_MS = 700


def desligado() -> bool:
    return os.environ.get("AXIL_SEM_ASSISTENTE") == "1"


class Assistente(QObject):
    diagnosticos = Signal(object, object)
    """(Path, list[Local]) — erros do Verible para um arquivo aberto."""
    lint_pronto = Signal(object)
    """ResultadoLint do Verilator para o projeto inteiro."""
    estado_linguagem = Signal(str, str)
    """("iniciando" | "ativo" | "indisponivel" | "parado", detalhe)"""
    estado_lint = Signal(str, str)
    """("rodando" | "pronto" | "indisponivel", detalhe)"""

    _resposta = Signal(int, object, object)
    _notificacao = Signal(str, object)
    _caiu = Signal(str)

    def __init__(
        self,
        fabrica_cliente: Callable[..., object] | None = None,
        fabrica_lint: Callable[[], object] | None = None,
    ) -> None:
        super().__init__()
        self._fabrica_cliente = fabrica_cliente
        self._fabrica_lint = fabrica_lint
        self.projeto: Projeto | None = None
        self.cliente = None
        self._geracao = 0
        self._abertos: dict[Path, str] = {}
        self._respostas: dict[int, Callable[[object, str | None], None]] = {}
        self._proximo = 0
        self._lint_rodando = False
        self._lint_de_novo = False
        self._tarefas: list[tarefas.Tarefa] = []
        self._espera_lint = QTimer(self)
        self._espera_lint.setSingleShot(True)
        self._espera_lint.setInterval(ESPERA_LINT_MS)
        self._espera_lint.timeout.connect(self._rodar_lint)
        self._resposta.connect(self._entregar)
        self._notificacao.connect(self._notificado)
        self._caiu.connect(self._servidor_caiu)

    @property
    def ativo(self) -> bool:
        return self.cliente is not None

    def _rodar(self, funcao, ao_concluir, ao_falhar) -> None:
        tarefa = tarefas.em_segundo_plano(funcao, self)
        tarefa.concluido.connect(ao_concluir)
        tarefa.falhou.connect(ao_falhar)
        self._tarefas = [x for x in self._tarefas if x.rodando] + [tarefa]
        tarefa.iniciar()

    # --- projeto -------------------------------------------------------------------------------

    def definir_projeto(self, projeto: Projeto | None) -> None:
        self._parar_cliente()
        self.projeto = projeto
        self._abertos.clear()
        if projeto is None or desligado():
            self.estado_linguagem.emit("parado", "")
            return
        self.reiniciar()
        self.conferir(agora=True)

    def reiniciar(self) -> None:
        """Sobe (de novo) o servidor — por exemplo, depois de criar um arquivo no projeto."""
        projeto = self.projeto
        if projeto is None or desligado():
            return
        self._parar_cliente()
        self._geracao += 1
        geracao = self._geracao
        self.estado_linguagem.emit("iniciando", "")
        fabrica = self._fabrica_cliente
        if fabrica is None:
            from axillares.motor.linguagem import ClienteLinguagem

            fabrica = ClienteLinguagem

        def subir():
            cliente = fabrica(
                projeto.raiz,
                projeto.arquivos_rtl() + projeto.arquivos_testbench(),
                ao_notificar=lambda m, p: self._notificacao.emit(m, p),
                ao_terminar=lambda motivo: self._caiu.emit(motivo),
            )
            try:
                cliente.iniciar()
            except Exception:
                cliente.encerrar()
                raise
            return cliente

        def pronto(cliente) -> None:
            if geracao != self._geracao:  # trocou de projeto enquanto subia
                _encerrar_em_segundo_plano(cliente)
                return
            self.cliente = cliente
            for caminho, texto in self._abertos.items():
                cliente.abrir(caminho, texto)
            self.estado_linguagem.emit("ativo", "Verible")

        def falhou(mensagem: str) -> None:
            if geracao == self._geracao:
                self.estado_linguagem.emit("indisponivel", mensagem)

        self._rodar(subir, pronto, falhou)

    def _parar_cliente(self) -> None:
        self._geracao += 1
        cliente, self.cliente = self.cliente, None
        for ao_responder in self._respostas.values():
            ao_responder(None, "cancelado")
        self._respostas.clear()
        if cliente is not None:
            _encerrar_em_segundo_plano(cliente)

    def _servidor_caiu(self, motivo: str) -> None:
        self.cliente = None
        self.estado_linguagem.emit("indisponivel", motivo)

    def encerrar(self) -> None:
        """Ao fechar o projeto ou o app: encerra o servidor sem deixar contêiner para trás."""
        self._geracao += 1
        self._espera_lint.stop()
        cliente, self.cliente = self.cliente, None
        if cliente is not None:
            cliente.encerrar()

    # --- documentos ----------------------------------------------------------------------------

    @staticmethod
    def e_hdl(caminho: Path) -> bool:
        return caminho.suffix.lower() in EXTENSOES_HDL

    def abrir(self, caminho: Path, texto: str) -> None:
        if not self.e_hdl(caminho):
            return
        self._abertos[caminho] = texto
        if self.cliente is not None:
            self._seguro(lambda: self.cliente.abrir(caminho, texto))

    def mudar(self, caminho: Path, texto: str) -> None:
        if not self.e_hdl(caminho):
            return
        self._abertos[caminho] = texto
        if self.cliente is not None:
            self._seguro(lambda: self.cliente.mudar(caminho, texto))

    def fechar(self, caminho: Path) -> None:
        if self._abertos.pop(caminho, None) is not None and self.cliente is not None:
            self._seguro(lambda: self.cliente.fechar(caminho))

    def _seguro(self, funcao: Callable[[], None]) -> None:
        try:
            funcao()
        except Exception as erro:  # servidor caiu no meio: o editor segue sem ele
            self._servidor_caiu(str(erro))

    def pedir(
        self, metodo: str, params: dict, ao_responder: Callable[[object, str | None], None]
    ) -> None:
        """`ao_responder(resultado, erro)` é chamado na thread da interface."""
        if self.cliente is None:
            ao_responder(None, "O servidor de linguagem não está ativo.")
            return
        self._proximo += 1
        ident = self._proximo
        self._respostas[ident] = ao_responder
        cliente = self.cliente
        self._seguro(
            lambda: cliente.pedir(metodo, params, lambda r, e: self._resposta.emit(ident, r, e))
        )

    def _entregar(self, ident: int, resultado: object, erro: object) -> None:
        ao_responder = self._respostas.pop(ident, None)
        if ao_responder is not None:
            ao_responder(resultado, erro)

    def _notificado(self, metodo: str, params: object) -> None:
        if metodo == "textDocument/publishDiagnostics" and self.projeto is not None:
            from axillares.motor.linguagem import diagnosticos

            caminho, locais = diagnosticos(params, self.projeto.raiz)  # type: ignore[arg-type]
            self.diagnosticos.emit(caminho, locais)

    # --- lint ----------------------------------------------------------------------------------

    def conferir(self, agora: bool = False) -> None:
        """Pede um lint do projeto; vários pedidos seguidos viram um só."""
        if self.projeto is None or desligado():
            return
        if agora:
            self._rodar_lint()
        else:
            self._espera_lint.start()

    def _rodar_lint(self) -> None:
        if self._lint_rodando:
            self._lint_de_novo = True
            return
        projeto = self.projeto
        if projeto is None:
            return
        self._lint_rodando = True
        self.estado_lint.emit("rodando", "")
        fabrica = self._fabrica_lint
        if fabrica is None:
            from axillares.motor.lint_verilator import LintVerilator

            fabrica = LintVerilator

        def terminou(resultado) -> None:
            self._lint_rodando = False
            if projeto is self.projeto:
                self.lint_pronto.emit(resultado)
                self.estado_lint.emit("pronto", "")
            self._de_novo()

        def falhou(mensagem: str) -> None:
            self._lint_rodando = False
            if projeto is self.projeto:
                self.estado_lint.emit("indisponivel", mensagem)
            self._de_novo()

        self._rodar(lambda: fabrica().verificar(projeto), terminou, falhou)

    def _de_novo(self) -> None:
        if self._lint_de_novo:
            self._lint_de_novo = False
            self._espera_lint.start()


def _encerrar_em_segundo_plano(cliente) -> None:
    import threading

    threading.Thread(target=cliente.encerrar, daemon=True).start()


def locais_por_arquivo(raiz: Path, locais: list[Local]) -> dict[Path, list[Local]]:
    saida: dict[Path, list[Local]] = {}
    for x in locais:
        saida.setdefault((raiz / x.arquivo).resolve(), []).append(x)
    return saida
