"""Posições e fios pelo ELK (Eclipse Layout Kernel, elkjs) — .

O ELK "layered" é o algoritmo de desenho de esquemáticos que o netlistsvg (do ecossistema Yosys)
usa: blocos em colunas pela direção do sinal, pinos em posição fixa no símbolo, fios em ângulos
retos que contornam os blocos, fan-out desenhado como árvore com pontos de junção, realimentação
contornando por fora. Aqui só se traduz o modelo para o JSON do ELK e de volta; quem calcula é o
elkjs, no Node da imagem fixada (layout_elk.js). Fixtures reais em tests/fixtures/esquema/.
"""

from __future__ import annotations

from axillares.core.esquema import Esquema, calcular_juncoes

MARGEM = 24.0
ROTULO_EMBAIXO = {"and", "or", "xor", "nand", "nor", "xnor", "not", "buf", "tribuf"}
LADOS = {"w": "WEST", "e": "EAST", "n": "NORTH", "s": "SOUTH"}

_OPCOES_COMUNS = {
    "elk.algorithm": "layered",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.layered.feedbackEdges": "true",
    "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
    "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
    "elk.layered.layering.strategy": "NETWORK_SIMPLEX",
    "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
    "elk.layered.thoroughness": "20",
    "elk.layered.unnecessaryBendpoints": "false",
    "elk.layered.mergeEdges": "false",
    "elk.separateConnectedComponents": "false",
    "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    "elk.padding": f"[top={MARGEM},left={MARGEM},bottom={MARGEM},right={MARGEM}]",
}
OPCOES = {
    # circuito: o sinal corre da esquerda para a direita
    "LR": _OPCOES_COMUNS
    | {
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "28",
        "elk.layered.spacing.nodeNodeBetweenLayers": "56",
        "elk.spacing.edgeNode": "14",
        "elk.layered.spacing.edgeNodeBetweenLayers": "16",
        "elk.spacing.edgeEdge": "9",
        "elk.layered.spacing.edgeEdgeBetweenLayers": "9",
        "elk.spacing.portPort": "10",
    },
    # transistores: do VDD (em cima) ao terra (embaixo)
    "TB": _OPCOES_COMUNS
    | {
        "elk.direction": "DOWN",
        "elk.spacing.nodeNode": "46",
        "elk.layered.spacing.nodeNodeBetweenLayers": "30",
        "elk.spacing.edgeNode": "14",
        "elk.layered.spacing.edgeNodeBetweenLayers": "12",
        "elk.spacing.edgeEdge": "9",
        "elk.layered.spacing.edgeEdgeBetweenLayers": "9",
    },
}


def _id_porta(bloco: str, pino: str) -> str:
    return f"{bloco}::{pino}"


def grafo_elk(esq: Esquema) -> dict:
    """O esquema no JSON do ELK: tamanhos, pinos fixos no lugar do símbolo e ligações."""
    filhos = []
    for b in esq.blocos:
        # portas com nome embaixo (nand2, xor2…) reservam a linha do texto
        extra = 12.0 if b.simbolo in ROTULO_EMBAIXO and b.rotulo else 0.0
        if b.simbolo in {"registrador", "latch"}:
            extra = 16.0  # o selo "Q = …" da simulação
        no: dict = {"id": b.id, "width": round(b.w, 2), "height": round(b.h + extra, 2)}
        opcoes: dict[str, str] = {}
        if b.simbolo == "juncao":
            opcoes["elk.portConstraints"] = "FREE"
        else:
            opcoes["elk.portConstraints"] = "FIXED_POS"
            no["ports"] = [
                {
                    "id": _id_porta(b.id, p.nome),
                    "x": round(p.x, 2),
                    "y": round(p.y, 2),
                    "width": 0,
                    "height": 0,
                    "layoutOptions": {"elk.port.side": LADOS.get(p.lado, "WEST")},
                }
                for p in b.pinos
            ]
        primeira = {"entrada", "bidir"} if esq.orientacao == "LR" else {"vdd"}
        ultima = {"saida"} if esq.orientacao == "LR" else {"gnd"}
        if b.simbolo in primeira:
            opcoes["elk.layered.layering.layerConstraint"] = "FIRST"
        elif b.simbolo in ultima:
            opcoes["elk.layered.layering.layerConstraint"] = "LAST"
        no["layoutOptions"] = opcoes
        filhos.append(no)
    juncoes = {b.id for b in esq.blocos if b.simbolo == "juncao"}

    def ponta(par: tuple[str, str]) -> str:
        return par[0] if par[0] in juncoes else _id_porta(*par)

    arestas = [
        {"id": f"e{k}", "sources": [ponta(lig.de)], "targets": [ponta(lig.para)]}
        for k, lig in enumerate(esq.ligacoes)
    ]
    return {
        "id": "raiz",
        "layoutOptions": OPCOES[esq.orientacao],
        "children": filhos,
        "edges": arestas,
    }


def aplicar_elk(esq: Esquema, resultado: dict) -> None:
    """Põe no esquema as posições, os fios (pontos de dobra) e as junções que o ELK calculou."""
    nos = {n["id"]: n for n in resultado.get("children", [])}
    for b in esq.blocos:
        n = nos.get(b.id)
        if n is not None:
            b.x, b.y = float(n.get("x", 0.0)), float(n.get("y", 0.0))
    arestas = {e["id"]: e for e in resultado.get("edges", [])}
    juncoes: set[tuple[float, float]] = set()
    for k, lig in enumerate(esq.ligacoes):
        e = arestas.get(f"e{k}")
        if not e or not e.get("sections"):
            lig.pontos = [esq.bloco(lig.de[0]).ponto(lig.de[1]),
                          esq.bloco(lig.para[0]).ponto(lig.para[1])]  # fmt: skip
            continue
        pontos: list[tuple[float, float]] = []
        for secao in e["sections"]:
            trecho = [secao["startPoint"], *secao.get("bendPoints", []), secao["endPoint"]]
            for p in trecho:
                xy = (round(float(p["x"]), 2), round(float(p["y"]), 2))
                if not pontos or pontos[-1] != xy:
                    pontos.append(xy)
        lig.pontos = pontos
        for j in e.get("junctionPoints", []) or []:
            juncoes.add((round(float(j["x"]), 1), round(float(j["y"]), 1)))
    esq.largura = float(resultado.get("width", 0.0))
    esq.altura = float(resultado.get("height", 0.0))
    calcular_juncoes(esq)
    esq.juncoes = sorted(set(esq.juncoes) | juncoes)
    esq.posicionado = True
