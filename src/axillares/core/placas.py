"""Placas FPGA, descritas em templates/placas/*.toml, e as restrições de pinos de um projeto.

Acrescentar uma placa é escrever um arquivo; nada aqui muda. O projeto mapeia as portas do
módulo de topo em recursos genéricos da placa (clk, btn0, led3…) e o Axillares gera o PCF ou o
LPF no formato que o nextpnr espera.
"""

from __future__ import annotations

import re
import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PASTA = Path(str(files("axillares.templates"))) / "placas"


class Recurso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pino: str
    nota: str = ""
    pull: str | None = None


class Placa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    nome: str
    fabricante: str
    familia: str = Field(pattern="^(ice40|ecp5|gowin)$")
    dispositivo: str
    pacote: str
    relogio_mhz: float
    restricoes: str = Field(pattern="^(pcf|lpf|cst)$")
    fluxo: str
    bitstream: str
    gravacao: str
    descricao: str
    fonte: str
    recursos: dict[str, Recurso]


class ErroPlaca(Exception):
    """Mensagem pronta para o usuário."""


def listar() -> list[Placa]:
    return [carregar(p.stem) for p in sorted(PASTA.glob("*.toml"))]


def carregar(ident: str) -> Placa:
    arquivo = PASTA / f"{ident}.toml"
    if not arquivo.is_file():
        disponiveis = ", ".join(p.stem for p in sorted(PASTA.glob("*.toml")))
        raise ErroPlaca(f"Placa “{ident}” desconhecida. Disponíveis: {disponiveis}.")
    return Placa.model_validate({**tomllib.loads(arquivo.read_text("utf-8")), "id": ident})


_PORTA = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\[\d+\])?$")


def gerar_restricoes(placa: Placa, mapeamento: dict[str, str]) -> str:
    """Arquivo de pinos (PCF ou LPF) a partir de {porta do módulo: recurso da placa}."""
    linhas = [
        f"# Gerado pelo Axillares para a placa {placa.nome} a partir de [fpga.pinos.{placa.id}]",
        f"# do axil.toml. Pinagem da placa: {placa.fonte}",
    ]
    for porta, recurso in mapeamento.items():
        if not _PORTA.match(porta):
            raise ErroPlaca(f"“{porta}” não é um nome de porta válido (ex.: clk, q[3]).")
        if recurso not in placa.recursos:
            raise ErroPlaca(
                f"A placa {placa.nome} não tem o recurso “{recurso}” (pedido para a porta "
                f"{porta}). Recursos: {', '.join(placa.recursos)}."
            )
        r = placa.recursos[recurso]
        if placa.restricoes == "pcf":
            linhas.append(f"set_io {porta} {r.pino}  # {recurso}")
        elif placa.restricoes == "lpf":
            pull = f" PULLMODE={r.pull}" if r.pull else ""
            linhas.append(f'LOCATE COMP "{porta}" SITE "{r.pino}";  # {recurso}')
            linhas.append(f'IOBUF PORT "{porta}"{pull} IO_TYPE=LVCMOS33;')
        else:
            raise ErroPlaca(f"Formato de restrições “{placa.restricoes}” ainda não suportado.")
    relogio = next((p for p, r in mapeamento.items() if r == "clk"), None)
    if relogio and placa.restricoes == "lpf":
        linhas.append(f'FREQUENCY PORT "{relogio}" {placa.relogio_mhz:g} MHZ;')
    return "\n".join(linhas) + "\n"
