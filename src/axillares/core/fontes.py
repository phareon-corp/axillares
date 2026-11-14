"""Arquivos do projeto para o editor: listar por grupo, ler e gravar com segurança.

Gravar é atômico (arquivo temporário + rename) e só vale dentro do projeto, nunca em runs/.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from string import Template

from axillares.core.projeto import ARQUIVO, Projeto

LIMITE_BYTES = 2 * 1024 * 1024
EXTENSOES_TEXTO = {
    ".v", ".sv", ".vh", ".svh", ".sdc", ".tcl", ".xdc", ".py", ".md", ".toml", ".txt",
    ".pcf", ".lpf", ".cst", ".sh", ".ini", ".yaml", ".yml", ".json",
}  # fmt: skip
IGNORAR = {"runs", ".git", "__pycache__", ".venv", "build", "sim_build"}


class ErroArquivo(Exception):
    """Mensagem pronta para o usuário."""


@dataclass(frozen=True)
class Grupo:
    nome: str
    arquivos: list[Path]


def agrupar(projeto: Projeto) -> list[Grupo]:
    """RTL, testbenches, restrições, projeto e outros — na ordem em que se trabalha."""
    rtl = projeto.arquivos_rtl()
    tbs = [a for a in projeto.arquivos_testbench() if a not in rtl]
    sdc = [projeto.arquivo_sdc()] if projeto.arquivo_sdc() else []
    vistos = set(rtl) | set(tbs) | set(sdc)
    projeto_ = [projeto.raiz / ARQUIVO]
    vistos |= set(projeto_)
    outros = []
    for pasta, subpastas, nomes in os.walk(projeto.raiz):
        subpastas[:] = sorted(s for s in subpastas if s not in IGNORAR and not s.startswith("."))
        for nome in sorted(nomes):
            caminho = (Path(pasta) / nome).resolve()
            if caminho.suffix.lower() in EXTENSOES_TEXTO and caminho not in vistos:
                outros.append(caminho)
    grupos = [
        Grupo("RTL", rtl),
        Grupo("Testbenches", tbs),
        Grupo("Restrições", [s for s in sdc if s.is_file()]),
        Grupo("Projeto", projeto_),
        Grupo("Outros", outros),
    ]
    return [g for g in grupos if g.arquivos]


def _dentro_do_projeto(projeto: Projeto, caminho: Path) -> Path:
    real = caminho.resolve()
    try:
        relativo = real.relative_to(projeto.raiz)
    except ValueError as erro:
        raise ErroArquivo(f"{caminho} está fora do projeto {projeto.nome}.") from erro
    if relativo.parts and relativo.parts[0] == "runs":
        raise ErroArquivo("Arquivos em runs/ são registros imutáveis de execuções; não se editam.")
    return real


def ler(projeto: Projeto, caminho: Path) -> str:
    real = _dentro_do_projeto(projeto, caminho)
    if not real.is_file():
        raise ErroArquivo(f"O arquivo {projeto.relativo(real)} não existe mais.")
    if real.stat().st_size > LIMITE_BYTES:
        raise ErroArquivo(f"{real.name} tem mais de 2 MB; abra-o num editor externo.")
    dados = real.read_bytes()
    if b"\0" in dados[:4096]:
        raise ErroArquivo(f"{real.name} parece binário; o editor só abre texto.")
    return dados.decode("utf-8", errors="replace")


def salvar(projeto: Projeto, caminho: Path, texto: str) -> None:
    real = _dentro_do_projeto(projeto, caminho)
    real.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=f".{real.name}.", dir=real.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as arquivo:
            arquivo.write(texto)
        if real.exists():
            os.chmod(temporario, real.stat().st_mode & 0o777)
        os.replace(temporario, real)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


# --- arquivo novo ------------------------------------------------------------------------------

PASTA_ESQUELETOS = Path(__file__).resolve().parent.parent / "templates" / "arquivos"
TIPOS_NOVO = {"modulo": "módulo (o circuito)", "testbench": "testbench (simulação)"}
_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ArquivoNovo:
    caminho: Path
    aviso: str | None = None
    """Quando o arquivo não casa com fontes.rtl/testbenches do axil.toml (o fluxo não o veria)."""


def esqueleto(nome_modulo: str, extensao: str, tipo: str = "modulo") -> str:
    modelo = PASTA_ESQUELETOS / f"{tipo}{extensao}"
    return Template(modelo.read_text(encoding="utf-8")).substitute(nome=nome_modulo)


def criar(projeto: Projeto, relativo: str, tipo: str = "modulo") -> ArquivoNovo:
    """Cria um arquivo Verilog/SystemVerilog com esqueleto. Nunca sobrescreve."""
    alvo = Path(relativo)
    if alvo.is_absolute() or ".." in alvo.parts:
        raise ErroArquivo("Use um caminho relativo ao projeto, como rtl/somador.sv.")
    extensao = alvo.suffix.lower()
    if extensao not in {".v", ".sv"}:
        raise ErroArquivo("O arquivo precisa terminar em .v (Verilog) ou .sv (SystemVerilog).")
    if not _IDENTIFICADOR.match(alvo.stem):
        raise ErroArquivo(
            f"“{alvo.stem}” não serve como nome de módulo: use letras, números e _, começando "
            "por letra."
        )
    if tipo not in TIPOS_NOVO:
        raise ErroArquivo(f"Tipo “{tipo}” desconhecido. Use: {', '.join(TIPOS_NOVO)}.")
    real = _dentro_do_projeto(projeto, projeto.raiz / alvo)
    if real.exists():
        raise ErroArquivo(f"{projeto.relativo(real)} já existe.")
    salvar(projeto, real, esqueleto(alvo.stem, extensao, tipo))
    lista = projeto.arquivos_testbench() if tipo == "testbench" else projeto.arquivos_rtl()
    aviso = None
    if real not in lista:
        campo = "fontes.testbenches" if tipo == "testbench" else "fontes.rtl"
        padroes = projeto.fontes.testbenches if tipo == "testbench" else projeto.fontes.rtl
        aviso = (
            f"{projeto.relativo(real)} foi criado, mas não casa com {campo} "
            f"({', '.join(padroes) or 'vazio'}) no axil.toml: o fluxo não vai lê-lo. Mova-o "
            "para a pasta certa ou acrescente o padrão."
        )
    return ArquivoNovo(real, aviso)
