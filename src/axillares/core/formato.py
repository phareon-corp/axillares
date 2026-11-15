"""Formatação para leitura humana, em português do Brasil. Usada pela CLI e pela GUI."""

from __future__ import annotations

import math
from datetime import datetime

from axillares.core.modelos import Situacao

ROTULO_SITUACAO = {
    Situacao.SUCESSO: "sucesso",
    Situacao.FALHA: "falha",
    Situacao.INTERROMPIDA: "interrompida",
    Situacao.EM_ANDAMENTO: "em andamento",
}

# chave → (rótulo curto para tabelas, casas decimais)
METRICAS_PRINCIPAIS = {
    "fmax_mhz": ("Fmax", 1),
    "area_total_um2": ("área", 1),
    "celulas": ("células", 0),
    "folga_setup_ns": ("folga", 2),
    "violacoes_drc": ("DRC", 0),
    "testes_passaram": ("passaram", 0),
    "testes_falharam": ("falharam", 0),
}


def numero(valor: float | None, casas: int = 2, sinal: bool = False) -> str:
    if valor is None:
        return "—"
    if valor == 0:
        return "0"
    if casas == 0 or (float(valor).is_integer() and abs(valor) >= 1):
        texto = f"{valor:,.0f}"
    else:
        texto = f"{valor:,.{casas}f}"
    texto = texto.replace(",", " ").replace(".", ",")
    if sinal and valor > 0:
        texto = "+" + texto
    return texto.replace("-", "−")


def casas_para(chave: str, *valores: float | None) -> int:
    """Casas decimais que mostram todos os valores sem esconder diferença nem precisão."""
    if chave in METRICAS_PRINCIPAIS:
        return METRICAS_PRINCIPAIS[chave][1]
    presentes = [float(v) for v in valores if v is not None]
    if all(v.is_integer() for v in presentes):
        return 0
    menor = min((abs(v) for v in presentes if v), default=1.0)
    if menor < 1:
        return min(8, max(2, 2 - math.floor(math.log10(menor))))
    return 2


def duracao(segundos: float) -> str:
    if segundos < 10:
        return f"{numero(segundos, 1)} s"
    if segundos < 60:
        return f"{round(segundos)} s"
    minutos, seg = divmod(round(segundos), 60)
    if minutos < 60:
        return f"{minutos} min {seg:02d} s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas} h {minutos:02d} min"


def momento(quando: datetime) -> str:
    agora = datetime.now(quando.tzinfo)
    if quando.date() == agora.date():
        return f"{quando:%H:%M}"
    return f"{quando:%d/%m %H:%M}"


def tamanho(nbytes: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unidade == "GB":
            return f"{numero(nbytes, 0 if unidade == 'B' else 1)} {unidade}"
        nbytes /= 1024
    return ""
