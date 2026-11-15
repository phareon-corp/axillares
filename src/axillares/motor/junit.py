"""results.xml do cocotb (formato JUnit) → casos de teste e métricas de Axillares.

Fixtures reais: tests/fixtures/cocotb/results-falha.xml (2 passam, 1 falha) e
results-passou.xml (2 passam, 1 pulado), gerados pelo cocotb 2.1 da imagem.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from axillares.core.modelos import CasoTeste, Metrica, SituacaoCaso
from axillares.motor.base import ErroMotor

RAIZ_NO_CONTEINER = "/projeto/"


def ler(texto: str) -> list[CasoTeste]:
    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError as erro:
        raise ErroMotor(f"O results.xml do cocotb está ilegível ({erro}).") from erro
    return [_caso(c) for c in raiz.iter("testcase")]


def _propriedades(caso: ET.Element) -> dict[str, str]:
    return {p.get("name", ""): p.get("value", "") for p in caso.iter("property")}


def _caso(caso: ET.Element) -> CasoTeste:
    props = _propriedades(caso)
    falha = caso.find("failure")
    if falha is None:
        falha = caso.find("error")
    pulado = caso.find("skipped")
    if falha is not None:
        situacao = SituacaoCaso.FALHOU
        mensagem = (falha.get("message") or "").strip().splitlines()
        detalhe = (falha.text or "").strip()
        resumo = mensagem[0] if mensagem else (detalhe.splitlines()[-1] if detalhe else "")
        tipo = falha.get("type", "")
        if tipo and tipo != "AssertionError" and resumo and not resumo.startswith(tipo):
            resumo = f"{tipo}: {resumo}"
    elif pulado is not None:
        situacao = SituacaoCaso.PULADO
        resumo, detalhe = (pulado.get("message") or "").strip(), ""
    else:
        situacao, resumo, detalhe = SituacaoCaso.PASSOU, "", ""
    arquivo = props.get("file", "")
    if arquivo.startswith(RAIZ_NO_CONTEINER):
        arquivo = arquivo[len(RAIZ_NO_CONTEINER) :]
    duracao_sim = props.get("sim_time_duration")
    unidade = props.get("sim_time_unit", "ns")
    return CasoTeste(
        nome=caso.get("name", "?"),
        modulo=caso.get("classname", ""),
        situacao=situacao,
        duracao_s=float(caso.get("time") or 0.0),
        tempo_simulado_ns=_em_ns(float(duracao_sim), unidade) if duracao_sim else None,
        mensagem=resumo,
        detalhe=detalhe,
        arquivo=arquivo,
        linha=int(props["line"]) if props.get("line", "").isdigit() else None,
    )


_FATORES_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}


def _em_ns(valor: float, unidade: str) -> float:
    return valor * _FATORES_NS.get(unidade, 1.0)


def metricas(casos: list[CasoTeste]) -> list[Metrica]:
    contar = {s: sum(1 for c in casos if c.situacao is s) for s in SituacaoCaso}
    simulado = sum(c.tempo_simulado_ns or 0.0 for c in casos)
    saida = [
        Metrica(chave="testes_total", valor=len(casos), rotulo="testes", origem="cocotb"),
        Metrica(chave="testes_passaram", valor=contar[SituacaoCaso.PASSOU], rotulo="passaram",
                origem="cocotb"),
        Metrica(chave="testes_falharam", valor=contar[SituacaoCaso.FALHOU], rotulo="falharam",
                origem="cocotb"),
        Metrica(chave="testes_pulados", valor=contar[SituacaoCaso.PULADO], rotulo="pulados",
                origem="cocotb"),
    ]  # fmt: skip
    if simulado:
        saida.append(
            Metrica(
                chave="tempo_simulado_ns",
                valor=simulado,
                unidade="ns",
                rotulo="tempo simulado",
                origem="cocotb",
            )
        )
    return saida
