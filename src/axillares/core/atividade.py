"""Análise de atividade de sinais digitais, a partir das mudanças que o leitor de ondas entrega.

São contas sobre a lista (tempo, valor) — nada de simulação nem de leitura de arquivo:
transições, fator de atividade, tempo em 1, frequência de sinais periódicos, pulso mais curto
(glitches), histograma de valores e medição entre dois cursores.

O fator de atividade α (transições por ciclo de relógio) é o que pesa no consumo dinâmico de um
circuito CMOS: P ≈ α · C · V² · f. Um relógio tem 2 transições por ciclo; um bit de dado que
muda a cada ciclo, 1.

Tempos de entrada em unidades da onda; `segundos_por_unidade` converte.
"""

from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass

Valor = int | str
NOMES_RELOGIO = ("clk", "clock", "clk_i", "i_clk", "ck", "relogio")


@dataclass(frozen=True)
class Atividade:
    nome: str
    largura: int
    transicoes: int
    """Para barramentos: bits que mudam, somados (distância de Hamming entre valores)."""
    subidas: int
    alto_pct: float | None
    """Só 1 bit: fração do tempo em 1, de 0 a 100."""
    desconhecido_pct: float
    """Fração do tempo em X ou Z."""
    periodo_s: float | None
    frequencia_hz: float | None
    periodico: bool
    pulso_min_s: float | None
    """O menor intervalo entre duas mudanças: pulsos curtos demais costumam ser glitches."""
    por_ciclo: float | None
    """Transições por ciclo do relógio de referência (o fator de atividade)."""


def _desconhecido(valor: Valor) -> bool:
    return isinstance(valor, str)


def _bits_que_mudam(a: Valor, b: Valor, largura: int) -> int:
    if _desconhecido(a) or _desconhecido(b):
        return 0 if a == b else 1
    return bin(int(a) ^ int(b)).count("1") if largura > 1 else int(a != b)


def duracoes(mudancas: list[tuple[int, Valor]], fim: int) -> list[tuple[Valor, int]]:
    """(valor, quanto tempo ficou) para cada trecho, do primeiro instante até `fim`."""
    saida = []
    for i, (t, v) in enumerate(mudancas):
        prox = mudancas[i + 1][0] if i + 1 < len(mudancas) else max(fim, t)
        saida.append((v, max(0, prox - t)))
    return saida


def analisar(
    nome: str,
    largura: int,
    mudancas: list[tuple[int, Valor]],
    fim: int,
    segundos_por_unidade: float,
    ciclos: int | None = None,
) -> Atividade:
    total = max(fim - (mudancas[0][0] if mudancas else 0), 1)
    transicoes = sum(_bits_que_mudam(a[1], b[1], largura) for a, b in itertools.pairwise(mudancas))
    trechos = duracoes(mudancas, fim)
    desconhecido = sum(d for v, d in trechos if _desconhecido(v))
    alto = None
    subidas_t: list[int] = []
    if largura == 1:
        alto = 100.0 * sum(d for v, d in trechos if v == 1) / total
        subidas_t = [b[0] for a, b in itertools.pairwise(mudancas) if a[1] == 0 and b[1] == 1]
    periodo = frequencia = None
    periodico = False
    if len(subidas_t) >= 3:
        intervalos = [b - a for a, b in itertools.pairwise(subidas_t)]
        medio = statistics.fmean(intervalos)
        # periódico: os intervalos entre subidas variam menos de 5%
        periodico = medio > 0 and statistics.pstdev(intervalos) <= 0.05 * medio
        if periodico:
            periodo = medio * segundos_por_unidade
            frequencia = 1.0 / periodo if periodo else None
    intervalos_todos = [b[0] - a[0] for a, b in itertools.pairwise(mudancas)]
    pulso = min(intervalos_todos) * segundos_por_unidade if intervalos_todos else None
    return Atividade(
        nome=nome,
        largura=largura,
        transicoes=transicoes,
        subidas=len(subidas_t),
        alto_pct=alto,
        desconhecido_pct=100.0 * desconhecido / total,
        periodo_s=periodo,
        frequencia_hz=frequencia,
        periodico=periodico,
        pulso_min_s=pulso,
        por_ciclo=(transicoes / ciclos) if ciclos else None,
    )


def relogio_de_referencia(candidatos: list[tuple[str, int, list[tuple[int, Valor]]]]) -> str | None:
    """O sinal que faz papel de relógio: pelo nome (clk, clock…) ou, sem nome conhecido, o sinal
    de 1 bit periódico com mais subidas. `candidatos`: (nome completo, largura, mudanças)."""
    um_bit = [(n, m) for n, larg, m in candidatos if larg == 1]
    for nome, _m in um_bit:
        if nome.rpartition(".")[2].lower() in NOMES_RELOGIO:
            return nome
    melhor, maior = None, 2
    for nome, mudancas in um_bit:
        a = analisar(nome, 1, mudancas, mudancas[-1][0] if mudancas else 0, 1.0)
        if a.periodico and a.subidas > maior:
            melhor, maior = nome, a.subidas
    return melhor


def histograma(mudancas: list[tuple[int, Valor]], fim: int) -> list[tuple[Valor, int]]:
    """Quanto tempo o sinal passou em cada valor, do maior para o menor."""
    soma: dict[Valor, int] = {}
    for v, d in duracoes(mudancas, fim):
        soma[v] = soma.get(v, 0) + d
    return sorted(soma.items(), key=lambda par: par[1], reverse=True)


def entre(mudancas: list[tuple[int, Valor]], t0: int, t1: int) -> int:
    """Quantas mudanças acontecem no intervalo (t0, t1]."""
    a, b = min(t0, t1), max(t0, t1)
    return sum(1 for t, _v in mudancas[1:] if a < t <= b)
