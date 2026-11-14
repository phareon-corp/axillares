"""Perfis de toolchain: declaração versionada do que deve existir e em que versão."""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PASTA_PERFIS = Path(__file__).parent / "perfis"
PERFIL_PADRAO = "iic-osic-2026.10"


class Origem(StrEnum):
    CONTEINER = "conteiner"
    NATIVA = "nativa"


class Comparacao(StrEnum):
    EXATA = "exata"
    MINIMA = "minima"


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Imagem(_Modelo):
    repositorio: str
    tag: str = Field(description="Informativa. O que vale é o digest.")
    digest: str
    camadas: int = Field(gt=0)
    tamanho_gb: float = Field(gt=0)
    caminhos: list[str] = Field(default_factory=list)

    @field_validator("digest")
    @classmethod
    def _digest_valido(cls, valor: str) -> str:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", valor):
            raise ValueError("o digest precisa ter a forma sha256:<64 dígitos hexadecimais>")
        return valor

    @property
    def referencia(self) -> str:
        """Referência fixada, a única forma usada para baixar e executar."""
        return f"{self.repositorio}@{self.digest}"


class Ferramenta(_Modelo):
    nome: str
    descricao: str
    origem: Origem
    versao: str
    comparacao: Comparacao = Comparacao.EXATA
    essencial: bool = True
    comando: list[str] = Field(min_length=1)
    expressao: str
    pacote: str | None = Field(default=None, description="Nome do pacote na distribuição.")
    instrucao: str | None = Field(default=None, description="Como instalar, quando não há pacote.")
    flatpak: str | None = Field(
        default=None, description="ID no Flathub; usado quando a ferramenta não está no PATH."
    )

    @field_validator("expressao")
    @classmethod
    def _expressao_compila(cls, valor: str) -> str:
        try:
            compilada = re.compile(valor, flags=re.MULTILINE)
        except re.error as erro:
            raise ValueError(f"expressão regular inválida: {erro}") from erro
        if compilada.groups < 1:
            raise ValueError("a expressão precisa de um grupo de captura com a versão")
        return valor

    def extrair_versao(self, saida: str) -> str | None:
        achado = re.search(self.expressao, saida, flags=re.MULTILINE)
        return achado.group(1) if achado else None


class Perfil(_Modelo):
    nome: str
    versao: str
    descricao: str
    imagem: Imagem
    motores: dict[str, str] = Field(
        default_factory=dict, description="Versões dos orquestradores dentro da imagem."
    )
    camadas: dict[str, str] = Field(
        default_factory=dict, description="Arquivo .lyp do KLayout por PDK, dentro da imagem."
    )
    visualizador: dict[str, str] = Field(
        default_factory=dict, description="Executáveis usados para visualizar, dentro da imagem."
    )
    editor: dict[str, str] = Field(
        default_factory=dict,
        description="Executáveis do editor (lint, servidor de linguagem), dentro da imagem.",
    )
    ferramentas: list[Ferramenta] = Field(min_length=1)

    @property
    def identificador(self) -> str:
        return f"{self.nome}-{self.versao}"

    def da_origem(self, origem: Origem) -> list[Ferramenta]:
        return [f for f in self.ferramentas if f.origem is origem]


class ErroPerfil(Exception):
    """Perfil ausente ou inválido. A mensagem já está pronta para o usuário."""


def listar_perfis() -> list[str]:
    return sorted(p.stem for p in PASTA_PERFIS.glob("*.toml"))


def carregar_perfil(nome_ou_caminho: str | Path = PERFIL_PADRAO) -> Perfil:
    """Carrega um perfil pelo nome (embutido no pacote) ou por caminho de arquivo."""
    caminho = Path(nome_ou_caminho)
    if caminho.suffix != ".toml":
        caminho = PASTA_PERFIS / f"{nome_ou_caminho}.toml"
    if not caminho.is_file():
        disponiveis = ", ".join(listar_perfis()) or "nenhum"
        raise ErroPerfil(
            f"Perfil “{nome_ou_caminho}” não encontrado. Perfis disponíveis: {disponiveis}."
        )
    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erro:
        raise ErroPerfil(f"O arquivo {caminho} não é TOML válido: {erro}.") from erro
    try:
        return Perfil.model_validate(dados)
    except ValidationError as erro:
        problemas = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in erro.errors()
        )
        raise ErroPerfil(f"O perfil {caminho.name} tem campos inválidos — {problemas}.") from erro


def comparar_versoes(encontrada: str, esperada: str, modo: Comparacao) -> bool:
    if modo is Comparacao.EXATA:
        return encontrada == esperada
    return _numeros(encontrada) >= _numeros(esperada)


def _numeros(versao: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", versao))
