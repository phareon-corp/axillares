"""Vocabulário de Axillares para execuções. Nenhum esquema de motor vaza para cá.

Os motores traduzem o que produzem para estes modelos na fronteira (src/axillares/motor/).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Etapa(StrEnum):
    """Etapas que um projeto pode executar."""

    SINTESE = "sintese"
    GDS = "gds"
    FPGA = "fpga"
    SIMULACAO = "sim"
    TESTE = "teste"

    @property
    def descricao(self) -> str:
        return {
            Etapa.SINTESE: "síntese lógica e temporização estimada",
            Etapa.GDS: "fluxo físico completo, do RTL ao GDSII",
            Etapa.FPGA: "síntese, posicionamento e roteamento numa FPGA, até o bitstream",
            Etapa.SIMULACAO: "simulação do testbench clássico, para olhar a onda",
            Etapa.TESTE: "testes automáticos em cocotb, com asserções que passam ou falham",
        }[self]

    @property
    def verifica(self) -> bool:
        """Simulação e teste conferem o comportamento; não produzem hardware."""
        return self in (Etapa.SIMULACAO, Etapa.TESTE)


class Situacao(StrEnum):
    SUCESSO = "sucesso"
    FALHA = "falha"
    INTERROMPIDA = "interrompida"
    EM_ANDAMENTO = "em andamento"


class TipoArtefato(StrEnum):
    GDS = "gds"
    NETLIST = "netlist"
    DEF = "def"
    LEF = "lef"
    SDF = "sdf"
    IMAGEM = "imagem"
    MANIFESTO = "manifesto"
    BITSTREAM = "bitstream"
    RELATORIO = "relatorio"
    ONDA = "onda"
    OUTRO = "outro"


class _Modelo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Metrica(_Modelo):
    chave: str = Field(description="Nome estável em Axillares, ex.: fmax_mhz.")
    valor: float
    unidade: str = ""
    rotulo: str = ""
    origem: str = Field(default="", description="Etapa do motor de onde o valor veio.")


class Artefato(_Modelo):
    nome: str
    tipo: TipoArtefato
    caminho: Path = Field(description="Relativo ao diretório da execução.")
    bytes: int = 0


class Local(_Modelo):
    """Um ponto no código-fonte apontado pelo motor ou pelo lint."""

    arquivo: str = Field(description="Relativo à raiz do projeto.")
    linha: int = Field(ge=1)
    coluna: int = Field(default=1, ge=1)
    mensagem: str
    gravidade: str = Field(default="erro", pattern="^(erro|aviso)$")
    origem: str = ""


class SituacaoCaso(StrEnum):
    PASSOU = "passou"
    FALHOU = "falhou"
    PULADO = "pulado"


class CasoTeste(_Modelo):
    """Um teste automático (cocotb): o nome, se passou, e por quê não, se falhou."""

    nome: str
    modulo: str = ""
    situacao: SituacaoCaso
    duracao_s: float = 0.0
    tempo_simulado_ns: float | None = None
    mensagem: str = Field(default="", description="Resumo da falha, uma linha.")
    detalhe: str = Field(default="", description="Traceback ou saída completa da falha.")
    arquivo: str = ""
    linha: int | None = None


class Falha(_Modelo):
    """Por que uma execução falhou, já em linguagem de gente."""

    resumo: str
    passo: str = Field(default="", description="Etapa do motor que falhou.")
    mensagens: list[str] = Field(default_factory=list, description="Linhas de erro do motor.")
    proximo_passo: str = ""
    locais: list[Local] = Field(default_factory=list, description="Onde no código, se souber.")


class ResultadoMotor(_Modelo):
    """O que um motor devolve depois de executar uma etapa."""

    situacao: Situacao
    versao_motor: str
    metricas: list[Metrica] = Field(default_factory=list)
    artefatos: list[Artefato] = Field(default_factory=list)
    falha: Falha | None = None
