"""Tradução do manifesto do SiliconCompiler (0.38.x) para o vocabulário de Axillares.

Único lugar do Axillares que conhece o esquema do manifesto. Testado contra manifestos reais em
tests/fixtures/siliconcompiler/. Quando o SiliconCompiler mudar o esquema, muda-se só aqui.

Esquema usado (0.38):
    metric.<nome>.node.<passo>.<índice>.value       valores por nó
    metric.<nome>.unit                              unidade (Hz, um^2, ns, mw…)
    record.status|starttime|endtime|scversion.node.<passo>.<índice>.value
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axillares.core.modelos import Falha, Local, Metrica, Situacao


@dataclass(frozen=True)
class _Mapa:
    chave: str
    rotulo: str
    unidade: str
    fator: float = 1.0
    agregacao: str = "ultimo"  # ultimo | soma | maximo


# nome no SiliconCompiler → métrica de Axillares
MAPA_METRICAS: dict[str, _Mapa] = {
    "fmax": _Mapa("fmax_mhz", "frequência máxima", "MHz", 1e-6),
    "setupslack": _Mapa("folga_setup_ns", "folga de setup", "ns"),
    "setupwns": _Mapa("wns_setup_ns", "pior folga negativa (setup)", "ns"),
    "setuptns": _Mapa("tns_setup_ns", "folga negativa total (setup)", "ns"),
    "holdslack": _Mapa("folga_hold_ns", "folga de hold", "ns"),
    "holdwns": _Mapa("wns_hold_ns", "pior folga negativa (hold)", "ns"),
    "cellarea": _Mapa("area_celulas_um2", "área de células", "µm²"),
    "totalarea": _Mapa("area_total_um2", "área total", "µm²"),
    "utilization": _Mapa("utilizacao_pct", "utilização", "%"),
    "cells": _Mapa("celulas", "células", ""),
    "registers": _Mapa("registradores", "registradores", ""),
    "buffers": _Mapa("buffers", "buffers", ""),
    "inverters": _Mapa("inversores", "inversores", ""),
    "nets": _Mapa("redes", "redes", ""),
    "pins": _Mapa("pinos", "pinos", ""),
    "logicdepth": _Mapa("profundidade_logica", "profundidade lógica", ""),
    "peakpower": _Mapa("potencia_pico_mw", "potência de pico", "mW"),
    "leakagepower": _Mapa("potencia_fuga_mw", "potência de fuga", "mW"),
    "wirelength": _Mapa("comprimento_fios_um", "comprimento de fios", "µm"),
    "vias": _Mapa("vias", "vias", ""),
    "drvs": _Mapa("violacoes_drv", "violações elétricas (DRV)", ""),
    "drcs": _Mapa("violacoes_drc", "violações de DRC", ""),
    "errors": _Mapa("erros", "erros relatados", "", agregacao="soma"),
    "warnings": _Mapa("avisos", "avisos relatados", "", agregacao="soma"),
    "totaltime": _Mapa("duracao_fluxo_s", "duração do fluxo", "s", agregacao="maximo"),
}

ROTULOS_PASSOS = {
    "elaborate": "leitura do RTL (elaboração)",
    "synthesis": "síntese lógica",
    "cleanup": "limpeza da netlist",
    "floorplan": "floorplan",
    "place": "posicionamento",
    "cts": "árvore de relógio",
    "route": "roteamento",
    "dfm": "preparação para fabricação",
    "write": "escrita dos arquivos finais",
    "timing": "análise de temporização",
}

PROXIMOS_PASSOS = {
    "elaborate": (
        "Corrija o erro no arquivo e linha indicados acima e execute de novo. Erros de "
        "elaboração costumam ser de sintaxe (um ; esquecido, um end a mais) ou de nome de módulo."
    ),
    "synthesis": (
        "A síntese não conseguiu transformar o RTL em portas lógicas. Confira se o módulo de "
        "topo no axil.toml é o certo e se não há construções só de simulação (initial, #atraso)."
    ),
    "floorplan": (
        "O floorplan não conseguiu montar o chip. Se o circuito é muito pequeno (poucas "
        "células), a malha de alimentação não cabe: fixe o tamanho do chip no axil.toml, na "
        "seção [asic], com chip_um = [40, 40] (largura e altura em µm)."
    ),
    "route": (
        "O roteamento não fechou. Tente reduzir a utilização (mais área) ou a frequência alvo."
    ),
}

_LINHA_SC = re.compile(r"^\|\s*(?P<nivel>\w+)\s*\|(?:[^|]*\|){3}\s?(?P<msg>.*)$")
_RUIDO = re.compile(r"reported \d+ errors during|^Halting |^Finished task|^Number of ")


_INICIO_NO = re.compile(
    r"^\|\s*INFO\s*\|\s*[^|]+\|\s*(?P<passo>[\w.]+)\s*\|\s*(?P<indice>\d+)\s*\|\s*Running in "
)


def passo_do_log(linha: str) -> str | None:
    """Rótulo legível quando a linha anuncia o início de um nó do fluxo; senão None."""
    achado = _INICIO_NO.match(linha)
    if not achado:
        return None
    passo = achado["passo"].rstrip(".")
    familia = passo.split(".")[0]
    rotulo = ROTULOS_PASSOS.get(familia, familia)
    return f"{rotulo} · {passo}"


def carregar(caminho: Path) -> dict[str, Any]:
    abrir = gzip.open if caminho.suffix == ".gz" else open
    with abrir(caminho, "rt", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _nos(entrada: dict[str, Any]) -> dict[tuple[str, str], Any]:
    valores: dict[tuple[str, str], Any] = {}
    for passo, indices in (entrada.get("node") or {}).items():
        if passo in {"default", "*"} or not isinstance(indices, dict):
            continue
        for indice, celula in indices.items():
            if indice in {"default", "*"}:
                continue
            valor = celula.get("value") if isinstance(celula, dict) else None
            if valor is not None:
                valores[(passo, indice)] = valor
    return valores


def ordem_dos_nos(manifesto: dict[str, Any]) -> list[tuple[str, str]]:
    """Nós executados, na ordem em que terminaram (início como desempate)."""
    record = manifesto.get("record", {})
    inicio = _nos(record.get("starttime", {}))
    fim = _nos(record.get("endtime", {}))
    nos = set(inicio) | set(fim)
    return sorted(nos, key=lambda n: (fim.get(n, inicio.get(n, "")), inicio.get(n, "")))


def situacao_dos_nos(manifesto: dict[str, Any]) -> dict[tuple[str, str], str]:
    return _nos(manifesto.get("record", {}).get("status", {}))


def versao_sc(manifesto: dict[str, Any]) -> str | None:
    versoes = set(_nos(manifesto.get("record", {}).get("scversion", {})).values())
    return next(iter(sorted(versoes)), None)


def situacao(manifesto: dict[str, Any]) -> Situacao:
    estados = situacao_dos_nos(manifesto).values()
    if any(e in {"error", "timeout"} for e in estados):
        return Situacao.FALHA
    if any(e == "success" for e in estados):
        return Situacao.SUCESSO
    return Situacao.FALHA


def metricas(manifesto: dict[str, Any]) -> list[Metrica]:
    ordem = ordem_dos_nos(manifesto)
    posicao = {no: i for i, no in enumerate(ordem)}
    bloco = manifesto.get("metric", {})
    resultado: list[Metrica] = []
    for nome_sc, mapa in MAPA_METRICAS.items():
        valores = _nos(bloco.get(nome_sc, {}))
        if not valores:
            continue
        nos = sorted(valores, key=lambda n: posicao.get(n, -1))
        if mapa.agregacao == "soma":
            valor, origem = float(sum(valores.values())), "fluxo inteiro"
        elif mapa.agregacao == "maximo":
            valor, origem = float(max(valores.values())), "fluxo inteiro"
        else:
            ultimo = nos[-1]
            valor, origem = float(valores[ultimo]), ".".join(ultimo).removesuffix(".0")
        resultado.append(
            Metrica(
                chave=mapa.chave,
                valor=round(valor * mapa.fator, 6),
                unidade=mapa.unidade,
                rotulo=mapa.rotulo,
                origem=origem,
            )
        )
    return resultado


def no_que_falhou(manifesto: dict[str, Any]) -> tuple[str, str] | None:
    estados = situacao_dos_nos(manifesto)
    for no in ordem_dos_nos(manifesto):
        if estados.get(no) in {"error", "timeout"}:
            return no
    falhos = [n for n, e in estados.items() if e in {"error", "timeout"}]
    return sorted(falhos)[0] if falhos else None


def mensagens_de_erro(log_do_no: str, raiz_no_conteiner: str = "/projeto/") -> list[str]:
    """Linhas ERROR do log de um nó, sem o prefixo do SiliconCompiler e sem ruído."""
    mensagens = []
    for linha in log_do_no.splitlines():
        achado = _LINHA_SC.match(linha)
        if not achado or achado["nivel"] != "ERROR":
            continue
        msg = achado["msg"].rstrip()
        if not msg.strip() or _RUIDO.search(msg.strip()):
            continue
        mensagens.append(msg.replace(raiz_no_conteiner, ""))
    return mensagens


# formato do slang (elaboração no SiliconCompiler 0.38): arquivo:linha:coluna: error: mensagem
_LOCAL = re.compile(
    r"^(?P<arquivo>[^\s:][^:]*):(?P<linha>\d+):(?P<coluna>\d+):\s*"
    r"(?P<gravidade>error|warning|fatal error):\s*(?P<mensagem>.+)$"
)


def locais_das_mensagens(mensagens: list[str], origem: str = "") -> list[Local]:
    locais = []
    for m in mensagens:
        achado = _LOCAL.match(m.strip())
        if achado:
            locais.append(
                Local(
                    arquivo=achado["arquivo"],
                    linha=int(achado["linha"]),
                    coluna=int(achado["coluna"]),
                    mensagem=achado["mensagem"].strip(),
                    gravidade="aviso" if achado["gravidade"] == "warning" else "erro",
                    origem=origem,
                )
            )
    return locais


def explicar_falha(
    manifesto: dict[str, Any], log_do_no: str = "", raiz_no_conteiner: str = "/projeto/"
) -> Falha:
    no = no_que_falhou(manifesto)
    if no is None:
        return Falha(
            resumo="O motor terminou sem concluir nenhuma etapa.",
            proximo_passo="Veja o log completo da execução.",
        )
    passo = no[0]
    familia = passo.split(".")[0]
    rotulo = ROTULOS_PASSOS.get(familia, passo)
    mensagens = mensagens_de_erro(log_do_no, raiz_no_conteiner)
    return Falha(
        resumo=f"A etapa de {rotulo} falhou.",
        passo=passo,
        mensagens=mensagens[:12],
        locais=locais_das_mensagens(mensagens, f"siliconcompiler · {passo}"),
        proximo_passo=PROXIMOS_PASSOS.get(
            familia, "Veja as mensagens acima; o log completo está em log.txt na execução."
        ),
    )
