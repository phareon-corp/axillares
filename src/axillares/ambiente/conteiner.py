"""Programa de contêiner (podman ou docker): detecção, presença da imagem, download e sonda.

Só a saída do podman é interpretada em detalhe, porque só dela temos fixtures reais
(tests/fixtures/podman/). Com docker o Axillares funciona, mas os erros caem no diagnóstico
genérico até que haja fixtures do docker.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from axillares.ambiente import diagnostico as dg
from axillares.ambiente.executor import Executor, Resultado
from axillares.ambiente.perfil import Ferramenta, Imagem

PROGRAMAS = ("podman", "docker")
VARIAVEL_PREFERENCIA = "AXIL_CONTEINER"

_SEM_PERMISSAO = re.compile(
    r"permission denied|cannot set up namespace|newuidmap|insufficient uids", re.IGNORECASE
)
_IMAGEM_DESCONHECIDA = re.compile(r"image not known", re.IGNORECASE)
_SEM_REDE = re.compile(
    r"connection refused|no such host|network is unreachable|i/o timeout|"
    r"tls handshake timeout|temporary failure in name resolution",
    re.IGNORECASE,
)
_MANIFESTO_DESCONHECIDO = re.compile(r"manifest unknown", re.IGNORECASE)
_CAMADA = re.compile(r"^Copying blob ", re.MULTILINE)


@dataclass(frozen=True)
class ProgramaConteiner:
    nome: str
    versao: str

    def __str__(self) -> str:
        return f"{self.nome} {self.versao}"


def detectar_programa(executor: Executor) -> ProgramaConteiner | None:
    """Podman primeiro (sem serviço em segundo plano, sem root); docker como alternativa.

    A variável AXIL_CONTEINER=docker inverte a preferência.
    """
    ordem = list(PROGRAMAS)
    if os.environ.get(VARIAVEL_PREFERENCIA) in PROGRAMAS:
        ordem.sort(key=lambda p: p != os.environ[VARIAVEL_PREFERENCIA])
    for nome in ordem:
        resultado = executor.executar([nome, "--version"], tempo_limite=15)
        if resultado.ok:
            achado = re.search(r"version\s+v?([\w.\-+]+?),?(?:\s|$)", resultado.saida)
            return ProgramaConteiner(nome, achado.group(1) if achado else "?")
    return None


class PresencaImagem(StrEnum):
    PRESENTE = "presente"
    AUSENTE = "ausente"
    ERRO = "erro"


@dataclass(frozen=True)
class ConsultaImagem:
    presenca: PresencaImagem
    digests: list[str]
    diagnostico: dg.Diagnostico | None = None


def consultar_imagem(
    programa: ProgramaConteiner, imagem: Imagem, executor: Executor
) -> ConsultaImagem:
    resultado = executor.executar(
        [programa.nome, "image", "inspect", "--format", "{{json .RepoDigests}}", imagem.referencia],
        tempo_limite=30,
    )
    if resultado.ok:
        return ConsultaImagem(PresencaImagem.PRESENTE, _digests(resultado.saida))
    if _SEM_PERMISSAO.search(resultado.saida):
        diag = dg.conteiner_sem_permissao(programa.nome, resultado.saida)
        return ConsultaImagem(PresencaImagem.ERRO, [], diag)
    if programa.nome == "docker" or _IMAGEM_DESCONHECIDA.search(resultado.saida):
        # docker: sem fixture real para distinguir "não existe" de outros erros; a leitura
        # conservadora é tratar como ausente, porque o próximo passo (instalar) é o mesmo.
        diag = dg.imagem_ausente(imagem.referencia, imagem.tamanho_gb)
        return ConsultaImagem(PresencaImagem.AUSENTE, [], diag)
    diag = dg.conteiner_falhou(programa.nome, "consultar a imagem", resultado.saida)
    return ConsultaImagem(PresencaImagem.ERRO, [], diag)


def _digests(saida: str) -> list[str]:
    try:
        lista = json.loads(saida.strip() or "[]")
    except json.JSONDecodeError:
        return re.findall(r"sha256:[0-9a-f]{64}", saida)
    return [r.rpartition("@")[2] for r in lista or [] if "@" in r]


def digest_confere(imagem: Imagem, digests: list[str]) -> bool:
    return imagem.digest in digests


# --- Download ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Progresso:
    camadas: int
    total: int
    linha: str


@dataclass(frozen=True)
class ResultadoInstalacao:
    ok: bool
    diagnostico: dg.Diagnostico | None
    resultado: Resultado


def baixar_imagem(
    programa: ProgramaConteiner,
    imagem: Imagem,
    executor: Executor,
    ao_progredir: Callable[[Progresso], None] = lambda _p: None,
) -> ResultadoInstalacao:
    """Baixa a imagem pelo digest e confere o digest depois. Retomável: camadas já
    baixadas não são baixadas de novo (isso é do próprio programa de contêiner)."""
    contagem = 0

    def receber(linha: str) -> None:
        nonlocal contagem
        if _CAMADA.match(linha):
            contagem += 1
        ao_progredir(Progresso(min(contagem, imagem.camadas), imagem.camadas, linha))

    resultado = executor.transmitir([programa.nome, "pull", imagem.referencia], receber)
    if not resultado.ok:
        return ResultadoInstalacao(
            False, classificar_falha_de_download(programa, imagem, resultado), resultado
        )

    consulta = consultar_imagem(programa, imagem, executor)
    if consulta.presenca is not PresencaImagem.PRESENTE:
        return ResultadoInstalacao(False, consulta.diagnostico, resultado)
    if not digest_confere(imagem, consulta.digests):
        return ResultadoInstalacao(
            False, dg.digest_divergente(imagem.digest, consulta.digests), resultado
        )
    ao_progredir(Progresso(imagem.camadas, imagem.camadas, "imagem verificada"))
    return ResultadoInstalacao(True, None, resultado)


def classificar_falha_de_download(
    programa: ProgramaConteiner, imagem: Imagem, resultado: Resultado
) -> dg.Diagnostico:
    saida = resultado.saida
    if _SEM_PERMISSAO.search(saida):
        return dg.conteiner_sem_permissao(programa.nome, saida)
    if _MANIFESTO_DESCONHECIDO.search(saida):
        return dg.digest_inexistente(imagem.referencia, saida)
    if _SEM_REDE.search(saida):
        return dg.sem_rede(saida)
    return dg.conteiner_falhou(programa.nome, "baixar a imagem", saida)


# --- Sonda: roda todos os comandos de versão num único contêiner ------------------------------

_INICIO = "@@axil:inicio:"
_FIM = "@@axil:fim:"


def script_de_sonda(imagem: Imagem, ferramentas: list[Ferramenta]) -> str:
    partes = []
    if imagem.caminhos:
        partes.append(f'export PATH="{":".join(imagem.caminhos)}:$PATH"')
    for f in ferramentas:
        partes.append(
            f"echo {shlex.quote(_INICIO + f.nome)}; "
            f"{shlex.join(f.comando)} </dev/null 2>&1; "
            f'echo "{_FIM}{f.nome}:$?"'
        )
    return "\n".join(partes)


def comando_de_sonda(
    programa: ProgramaConteiner, imagem: Imagem, ferramentas: list[Ferramenta]
) -> list[str]:
    return [
        programa.nome, "run", "--rm", "--network=none", "--entrypoint", "sh",
        imagem.referencia, "-c", script_de_sonda(imagem, ferramentas),
    ]  # fmt: skip


def separar_sonda(saida: str) -> dict[str, Resultado]:
    """Divide a saída combinada da sonda em um resultado por ferramenta."""
    resultados: dict[str, Resultado] = {}
    atual: str | None = None
    linhas: list[str] = []
    for linha in saida.splitlines():
        if linha.startswith(_INICIO):
            atual, linhas = linha[len(_INICIO) :], []
        elif linha.startswith(_FIM) and atual is not None:
            nome, _, codigo = linha[len(_FIM) :].rpartition(":")
            if nome == atual:
                resultados[nome] = Resultado(
                    int(codigo) if codigo.isdigit() else 1, "\n".join(linhas)
                )
                atual = None
        elif atual is not None:
            linhas.append(linha)
    return resultados


def sondar(
    programa: ProgramaConteiner, imagem: Imagem, ferramentas: list[Ferramenta], executor: Executor
) -> tuple[dict[str, Resultado], Resultado]:
    resultado = executor.executar(comando_de_sonda(programa, imagem, ferramentas), tempo_limite=180)
    return separar_sonda(resultado.saida), resultado
