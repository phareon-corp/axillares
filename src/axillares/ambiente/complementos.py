"""Complementos: arquivos pequenos de terceiros que a imagem de ferramentas não traz.

Hoje só o elkjs (o ELK, que posiciona o esquemático). Como as ferramentas, não entram no
repositório nem no pacote: são baixados uma vez, na versão fixada no perfil, conferidos pelo hash
de integridade que o registro publica (sha512 do npm) e guardados em ~/.cache/axillares. Rodam
dentro do contêiner, sem rede.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

TEMPO_LIMITE_S = 60


class Complemento(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    versao: str
    url: str
    integridade: str
    """Formato SRI do npm: "sha512-<base64>"."""
    arquivo: str
    """Caminho do arquivo útil dentro do pacote .tgz."""
    licenca: str

    @field_validator("integridade")
    @classmethod
    def _sri(cls, valor: str) -> str:
        if not valor.startswith("sha512-"):
            raise ValueError("a integridade precisa ser sha512-<base64>, como o npm publica")
        return valor


class ErroComplemento(Exception):
    """Download ou conferência falhou. A mensagem já está pronta para o usuário."""


def pasta_cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "axillares" / "complementos"


def pasta_do(nome: str, c: Complemento) -> Path:
    return pasta_cache() / f"{nome}-{c.versao}"


def conferir(dados: bytes, integridade: str) -> bool:
    algoritmo, _, esperado = integridade.partition("-")
    obtido = base64.b64encode(hashlib.new(algoritmo, dados).digest()).decode()
    return obtido == esperado


def extrair(pacote: bytes, membro: str) -> bytes:
    """Só o arquivo pedido, lido da memória — nada do pacote é escrito no disco além dele."""
    with tarfile.open(fileobj=io.BytesIO(pacote), mode="r:gz") as tar:
        try:
            info = tar.getmember(membro)
        except KeyError as erro:
            raise ErroComplemento(f"O pacote não tem {membro}.") from erro
        if not info.isfile():
            raise ErroComplemento(f"{membro} no pacote não é um arquivo comum.")
        arquivo = tar.extractfile(info)
        assert arquivo is not None
        return arquivo.read()


def _baixar(url: str) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": "axillares"})
    with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE_S) as resposta:
        return resposta.read()


def garantir(
    nome: str,
    c: Complemento,
    ao_progresso: Callable[[str], None] | None = None,
    baixar: Callable[[str], bytes] = _baixar,
) -> Path:
    """A pasta com o arquivo do complemento, baixando e conferindo se ainda não estiver lá."""
    pasta = pasta_do(nome, c)
    destino = pasta / Path(c.arquivo).name
    marca = pasta / ".integridade"
    if destino.is_file() and marca.is_file() and marca.read_text().strip() == c.integridade:
        return pasta
    if ao_progresso:
        ao_progresso(f"Baixando o {nome} {c.versao} (uma vez só)")
    try:
        pacote = baixar(c.url)
    except OSError as erro:
        raise ErroComplemento(
            f"Não consegui baixar o {nome} {c.versao} de {c.url} ({erro}). Ele é preciso uma vez "
            "só, para desenhar o esquemático; confira a conexão e tente de novo."
        ) from erro
    if not conferir(pacote, c.integridade):
        raise ErroComplemento(
            f"O {nome} baixado não confere com o hash fixado no perfil — o arquivo foi alterado "
            "no caminho ou no registro. Nada foi instalado."
        )
    conteudo = extrair(pacote, c.arquivo)
    pasta.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=pasta, prefix=".baixando-")
    with os.fdopen(fd, "wb") as f:
        f.write(conteudo)
    os.replace(temporario, destino)
    marca.write_text(c.integridade + "\n")
    return pasta
