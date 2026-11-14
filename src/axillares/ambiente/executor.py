"""Execução de processos externos.

É a única porta do Axillares para processos de terceiros: tudo o que roda uma ferramenta ou um
motor passa por um `Executor`. Nos testes, `ExecutorFalso` devolve saídas gravadas e nenhuma
ferramenta real é necessária.
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

CODIGO_NAO_ENCONTRADO = 127
CODIGO_TEMPO_ESGOTADO = 124
CODIGO_CANCELADO = -15


@dataclass(frozen=True)
class Resultado:
    codigo: int
    saida: str
    """stdout e stderr intercalados, como o usuário veria no terminal."""

    @property
    def ok(self) -> bool:
        return self.codigo == 0

    @property
    def nao_encontrado(self) -> bool:
        return self.codigo == CODIGO_NAO_ENCONTRADO

    @property
    def tempo_esgotado(self) -> bool:
        return self.codigo == CODIGO_TEMPO_ESGOTADO


class Executor(Protocol):
    def executar(self, comando: Sequence[str], *, tempo_limite: float = 60) -> Resultado: ...

    def transmitir(
        self,
        comando: Sequence[str],
        ao_receber: Callable[[str], None],
        cancelar: threading.Event | None = None,
    ) -> Resultado: ...


class ExecutorReal:
    """Executa processos de verdade, sem shell, com saída em texto UTF-8."""

    def __init__(self, ambiente: dict[str, str] | None = None) -> None:
        self._ambiente = {**os.environ, "LC_ALL": "C.UTF-8", **(ambiente or {})}

    def executar(self, comando: Sequence[str], *, tempo_limite: float = 60) -> Resultado:
        try:
            processo = subprocess.run(
                list(comando),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=tempo_limite,
                env=self._ambiente,
                check=False,
            )
        except FileNotFoundError:
            return Resultado(CODIGO_NAO_ENCONTRADO, f"{comando[0]}: comando não encontrado")
        except PermissionError as erro:
            return Resultado(126, f"{comando[0]}: {erro}")
        except subprocess.TimeoutExpired as erro:
            parcial = erro.output if isinstance(erro.output, str) else ""
            return Resultado(CODIGO_TEMPO_ESGOTADO, parcial)
        return Resultado(processo.returncode, processo.stdout)

    def transmitir(
        self,
        comando: Sequence[str],
        ao_receber: Callable[[str], None],
        cancelar: threading.Event | None = None,
    ) -> Resultado:
        """Executa transmitindo cada linha. Se `cancelar` for acionado, encerra o processo
        (SIGTERM e, depois de 5 s, SIGKILL) e devolve o que foi lido até ali."""
        linhas: list[str] = []
        try:
            processo = subprocess.Popen(
                list(comando),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=self._ambiente,
            )
        except FileNotFoundError:
            return Resultado(CODIGO_NAO_ENCONTRADO, f"{comando[0]}: comando não encontrado")

        terminou = threading.Event()
        if cancelar is not None:

            def vigiar() -> None:
                while not terminou.wait(0.2):
                    if cancelar.is_set():
                        processo.terminate()
                        try:
                            processo.wait(5)
                        except subprocess.TimeoutExpired:
                            processo.kill()
                        return

            threading.Thread(target=vigiar, daemon=True, name="axil-vigia").start()

        assert processo.stdout is not None
        try:
            for linha in processo.stdout:
                linha = linha.rstrip("\n")
                linhas.append(linha)
                ao_receber(linha)
        finally:
            codigo = processo.wait()
            terminou.set()
        return Resultado(codigo, "\n".join(linhas))


Casador = tuple[str, ...] | Callable[[Sequence[str]], bool]


@dataclass
class ExecutorFalso:
    """Devolve respostas gravadas. A primeira regra que casar com o comando vence.

    Uma regra casa por prefixo (`("podman", "--version")`) ou por função. Comando sem regra
    responde como "comando não encontrado", que é o que aconteceria numa máquina vazia.
    """

    regras: list[tuple[Casador, Resultado]] = field(default_factory=list)
    chamadas: list[tuple[str, ...]] = field(default_factory=list)

    def responder(self, casador: Casador, codigo: int = 0, saida: str = "") -> ExecutorFalso:
        self.regras.append((casador, Resultado(codigo, saida)))
        return self

    def _procurar(self, comando: Sequence[str]) -> Resultado:
        tupla = tuple(comando)
        self.chamadas.append(tupla)
        for casador, resultado in self.regras:
            casou = casador(tupla) if callable(casador) else tupla[: len(casador)] == casador
            if casou:
                return resultado
        return Resultado(CODIGO_NAO_ENCONTRADO, f"{comando[0]}: comando não encontrado")

    def executar(self, comando: Sequence[str], *, tempo_limite: float = 60) -> Resultado:
        return self._procurar(comando)

    def transmitir(
        self,
        comando: Sequence[str],
        ao_receber: Callable[[str], None],
        cancelar: threading.Event | None = None,
    ) -> Resultado:
        resultado = self._procurar(comando)
        for linha in resultado.saida.splitlines():
            if cancelar is not None and cancelar.is_set():
                return Resultado(CODIGO_CANCELADO, resultado.saida)
            ao_receber(linha)
        return resultado
