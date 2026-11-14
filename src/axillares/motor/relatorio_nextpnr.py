"""Tradução do relatório do nextpnr (--report, JSON) para métricas de Axillares.

Único lugar que conhece esse formato; testado contra relatórios reais em tests/fixtures/edalize/.
Formato usado: {"fmax": {<rede do relógio>: {"achieved": MHz, "constraint": MHz}},
                "utilization": {<tipo de bel>: {"used": n, "available": n}}}
"""

from __future__ import annotations

import re

from axillares.core.modelos import Falha, Metrica

# tipo de bel → (chave, rótulo) por família. Os outros tipos entram como "uso_<tipo>".
RECURSOS = {
    "ICESTORM_LC": ("celulas_logicas", "células lógicas (LUT + FF)"),
    "TRELLIS_COMB": ("celulas_logicas", "células lógicas (LUT)"),
    "TRELLIS_FF": ("flipflops", "flip-flops"),
    "ICESTORM_RAM": ("memorias_bram", "blocos de memória (BRAM)"),
    "DP16KD": ("memorias_bram", "blocos de memória (BRAM)"),
    "ICESTORM_DSP": ("dsps", "blocos DSP"),
    "MULT18X18D": ("dsps", "blocos DSP"),
    "SB_IO": ("pinos_fpga", "pinos de entrada e saída"),
    "TRELLIS_IO": ("pinos_fpga", "pinos de entrada e saída"),
}


def nome_do_relogio(rede: str) -> str:
    """'clk$SB_IO_IN_$glb_clk' → 'clk'; '$glbnet$clk$TRELLIS_IO_IN' → 'clk'."""
    partes = [p for p in rede.split("$") if p and p not in {"glbnet", "glb_clk"}]
    candidatos = [p for p in partes if not re.match(r"^(SB_|TRELLIS_)", p)]
    return candidatos[0] if candidatos else rede


def metricas(relatorio: dict) -> list[Metrica]:
    resultado: list[Metrica] = []
    relogios = relatorio.get("fmax", {})
    if relogios:
        pior = min(relogios.values(), key=lambda v: v["achieved"])
        resultado.append(
            Metrica(
                chave="fmax_mhz",
                valor=round(pior["achieved"], 3),
                unidade="MHz",
                rotulo="frequência máxima",
                origem="nextpnr",
            )
        )
        resultado.append(
            Metrica(
                chave="fmax_alvo_mhz",
                valor=round(pior["constraint"], 3),
                unidade="MHz",
                rotulo="frequência exigida",
                origem="nextpnr",
            )
        )
        resultado.append(
            Metrica(
                chave="folga_fmax_mhz",
                valor=round(pior["achieved"] - pior["constraint"], 3),
                unidade="MHz",
                rotulo="sobra de frequência",
                origem="nextpnr",
            )
        )
        for rede, v in relogios.items():
            nome = nome_do_relogio(rede)
            resultado.append(Metrica(chave=f"fmax_mhz_{nome}", valor=round(v["achieved"], 3),
                                     unidade="MHz", rotulo=f"Fmax do relógio {nome}",
                                     origem="nextpnr"))  # fmt: skip
    vistos: set[str] = set()
    for tipo, uso in relatorio.get("utilization", {}).items():
        if tipo not in RECURSOS:
            continue  # blocos internos (DCCA, SB_GB…) não dizem nada a quem está aprendendo
        chave, rotulo = RECURSOS[tipo]
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(Metrica(chave=chave, valor=uso["used"], rotulo=rotulo, origem=tipo))
        if uso.get("available"):
            resultado.append(Metrica(chave=f"{chave}_pct",
                                     valor=round(100 * uso["used"] / uso["available"], 2),
                                     unidade="%", rotulo=f"{rotulo} — % do dispositivo",
                                     origem=tipo))  # fmt: skip
    return resultado


def falha_de_temporizacao(relatorio: dict) -> Falha | None:
    """Se algum relógio não fechou, a falha diz isso na primeira linha, com o domínio."""
    falhos = [(rede, v) for rede, v in relatorio.get("fmax", {}).items()
              if v["achieved"] < v["constraint"]]  # fmt: skip
    if not falhos:
        return None
    rede, v = min(falhos, key=lambda x: x[1]["achieved"] - x[1]["constraint"])
    nome = nome_do_relogio(rede)
    from axillares.core.formato import numero

    return Falha(
        resumo=(
            f"A temporização não foi atendida no relógio {nome}: "
            f"{numero(v['achieved'], 1)} MHz alcançados, {numero(v['constraint'], 1)} MHz "
            "exigidos."
        ),
        passo="nextpnr",
        mensagens=[f"domínio de relógio: {nome} (rede {rede})"],
        proximo_passo=(
            "O caminho mais lento entre dois flip-flops não cabe no período do relógio da placa. "
            "Encurte a lógica entre registradores (divida a conta em dois ciclos, por exemplo) "
            "ou use uma frequência menor. O log completo está em log.txt."
        ),
    )
