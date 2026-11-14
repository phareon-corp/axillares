"""Lint do Verilator dentro da imagem fixada, lido pelo SARIF que ele mesmo escreve.

O Verilator 5.052 tem um defeito no SARIF: quando não há aviso (só erros), a lista de regras sai
vazia e falta a vírgula entre o objeto "tool" e "invocations" — JSON inválido. O reparo abaixo é
estreito: só é tentado se o JSON falhar, e só insere aquela vírgula
(tests/fixtures/verilator/so-erro.sarif é o arquivo real).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core import explicacoes as ex
from axillares.core.modelos import Local
from axillares.core.projeto import Projeto
from axillares.motor.base import ErroMotor

NO_CONTEINER_PROJETO = "/projeto"
NO_CONTEINER_SAIDA = "/saida"
# avisos de estilo que mais atrapalham do que ajudam quem está começando
DESLIGADOS = ("DECLFILENAME", "PINCONNECTEMPTY", "UNUSEDPARAM")
_VIRGULA_FALTANDO = re.compile(r'(\})(\s*)("invocations"\s*:)')
_FIM = re.compile(r"^Exiting due to ", re.IGNORECASE)


@dataclass(frozen=True)
class ResultadoLint:
    locais: list[Local] = field(default_factory=list)
    gerais: list[str] = field(default_factory=list)
    """Erros sem arquivo nem linha (módulo de topo inexistente, por exemplo)."""

    @property
    def erros(self) -> int:
        return sum(1 for x in self.locais if x.gravidade == "erro") + len(self.gerais)

    @property
    def avisos(self) -> int:
        return sum(1 for x in self.locais if x.gravidade == "aviso")


def ler_sarif(texto: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        reparado = _VIRGULA_FALTANDO.sub(r"\1,\2\3", texto, count=1)
        try:
            return json.loads(reparado)
        except json.JSONDecodeError as erro:
            raise ErroMotor(f"O Verilator escreveu um SARIF ilegível ({erro}).") from erro


def _relativo(uri: str, raiz_no_conteiner: str) -> str:
    caminho = unquote(urlparse(uri).path) if uri.startswith("file:") else uri
    prefixo = raiz_no_conteiner.rstrip("/") + "/"
    return caminho[len(prefixo) :] if caminho.startswith(prefixo) else caminho


def _mensagem(codigo: str | None, texto: str) -> str:
    primeira = texto.strip().splitlines()[0] if texto.strip() else ""
    explicacao = ex.aviso_de_lint(codigo) if codigo else None
    if explicacao is None:
        return f"{primeira} ({codigo})" if codigo else primeira
    return f"{explicacao.o_que} {explicacao.fazer} — {codigo}: {primeira}"


def traduzir(sarif: dict, raiz_no_conteiner: str = NO_CONTEINER_PROJETO) -> ResultadoLint:
    locais: list[Local] = []
    gerais: list[str] = []
    for run in sarif.get("runs", []):
        for r in run.get("results", []):
            texto = r.get("message", {}).get("text", "")
            gravidade = "erro" if r.get("level") == "error" else "aviso"
            codigo = r.get("ruleId")
            fisicos = [
                loc["physicalLocation"]
                for loc in r.get("locations", [])
                if "physicalLocation" in loc
            ]
            if not fisicos:
                if gravidade == "erro" and not _FIM.match(texto.strip()):
                    gerais.append(_mensagem(codigo, texto))
                continue
            fis = fisicos[0]
            regiao = fis.get("region", {})
            locais.append(
                Local(
                    arquivo=_relativo(fis["artifactLocation"]["uri"], raiz_no_conteiner),
                    linha=max(1, int(regiao.get("startLine", 1))),
                    coluna=max(1, int(regiao.get("startColumn", 1))),
                    mensagem=_mensagem(codigo, texto),
                    gravidade=gravidade,
                    origem="verilator" + (f" · {codigo}" if codigo else ""),
                )
            )
    locais.sort(key=lambda x: (x.gravidade != "erro", x.arquivo, x.linha, x.coluna))
    return ResultadoLint(locais, gerais)


class LintVerilator:
    nome = "verilator"

    def __init__(
        self,
        perfil: Perfil | None = None,
        executor: Executor | None = None,
        programa: ct.ProgramaConteiner | None = None,
    ) -> None:
        self.perfil = perfil or carregar_perfil()
        self.executor = executor or ExecutorReal()
        self._programa = programa

    def programa(self) -> ct.ProgramaConteiner:
        if self._programa is None:
            self._programa = ct.detectar_programa(self.executor)
        if self._programa is None:
            raise ErroMotor("Nem podman nem docker instalados; veja “axil ambiente situacao”.")
        return self._programa

    def comando(self, projeto: Projeto, saida: Path) -> list[str]:
        prog = self.programa()
        usuario = (
            ["--userns=keep-id"] if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )  # fmt: skip
        arquivos = [f"{NO_CONTEINER_PROJETO}/{projeto.relativo(a)}" for a in projeto.arquivos_rtl()]
        verilator = self.perfil.editor.get("verilator", "verilator")
        return [
            prog.nome, "run", "--rm", "--init", "--network=none", *usuario,
            "-v", f"{projeto.raiz}:{NO_CONTEINER_PROJETO}:ro,z",
            "-v", f"{saida}:{NO_CONTEINER_SAIDA}:z",
            "-e", "HOME=/tmp", "-w", NO_CONTEINER_PROJETO,
            "--entrypoint", verilator, self.perfil.imagem.referencia,
            "--lint-only", "-Wall", *(f"-Wno-{c}" for c in DESLIGADOS), "-Wno-fatal",
            "--top-module", projeto.projeto.topo,
            "--diagnostics-sarif", "--diagnostics-sarif-output", f"{NO_CONTEINER_SAIDA}/lint.sarif",
            *arquivos,
        ]  # fmt: skip

    def verificar(self, projeto: Projeto) -> ResultadoLint:
        with tempfile.TemporaryDirectory(prefix="axil-lint-") as pasta:
            saida = Path(pasta)
            resultado = self.executor.executar(self.comando(projeto, saida), tempo_limite=120)
            sarif = saida / "lint.sarif"
            if not sarif.is_file():
                detalhe = "\n".join(resultado.saida.strip().splitlines()[-4:])
                raise ErroMotor(f"O Verilator não produziu o relatório de lint.\n{detalhe}".strip())
            return traduzir(ler_sarif(sarif.read_text(encoding="utf-8")))
