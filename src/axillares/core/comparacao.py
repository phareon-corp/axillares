"""Comparação de duas execuções — alimenta `axil comparar` e a tela de comparação."""

from __future__ import annotations

from dataclasses import dataclass

from axillares.core.caderno import RegistroExecucao

# Métricas mostradas primeiro, nesta ordem; as demais vêm depois, em ordem alfabética.
PRIORIDADE = (
    "fmax_mhz",
    "folga_setup_ns",
    "wns_setup_ns",
    "folga_hold_ns",
    "area_celulas_um2",
    "area_total_um2",
    "utilizacao_pct",
    "celulas",
    "registradores",
    "potencia_pico_mw",
    "comprimento_fios_um",
    "violacoes_drc",
    "violacoes_drv",
    "duracao_fluxo_s",
)

# Para estas, valor maior é melhor; para as demais com sentido claro, menor é melhor.
MAIOR_E_MELHOR = {"fmax_mhz", "folga_setup_ns", "folga_hold_ns"}
MENOR_E_MELHOR = {
    "area_celulas_um2", "area_total_um2", "celulas", "potencia_pico_mw", "potencia_fuga_mw",
    "comprimento_fios_um", "violacoes_drc", "violacoes_drv", "erros", "avisos",
    "duracao_fluxo_s", "wns_setup_ns", "tns_setup_ns",
}  # fmt: skip


@dataclass(frozen=True)
class LinhaComparacao:
    chave: str
    rotulo: str
    unidade: str
    a: float | None
    b: float | None

    @property
    def delta(self) -> float | None:
        if self.a is None or self.b is None:
            return None
        return self.b - self.a

    @property
    def delta_pct(self) -> float | None:
        if self.delta is None or not self.a:
            return None
        return 100.0 * self.delta / abs(self.a)

    @property
    def tendencia(self) -> str:
        """melhor | pior | igual | neutra — de A para B."""
        d = self.delta
        if d is None or abs(d) < 1e-9:
            return "igual" if d is not None else "neutra"
        if self.chave in MAIOR_E_MELHOR:
            return "melhor" if d > 0 else "pior"
        if self.chave in MENOR_E_MELHOR:
            return "melhor" if d < 0 else "pior"
        return "neutra"


@dataclass(frozen=True)
class Comparacao:
    a: RegistroExecucao
    b: RegistroExecucao
    linhas: list[LinhaComparacao]

    @property
    def mesmo_rtl(self) -> bool:
        return self.a.hash_rtl == self.b.hash_rtl

    @property
    def mesma_etapa(self) -> bool:
        return self.a.etapa == self.b.etapa

    @property
    def mesma_versao_motor(self) -> bool:
        return (self.a.motor, self.a.versao_motor) == (self.b.motor, self.b.versao_motor)


def comparar(a: RegistroExecucao, b: RegistroExecucao) -> Comparacao:
    ma = {m.chave: m for m in a.metricas}
    mb = {m.chave: m for m in b.metricas}
    chaves = set(ma) | set(mb)
    ordem = [c for c in PRIORIDADE if c in chaves] + sorted(chaves - set(PRIORIDADE))
    linhas = []
    for chave in ordem:
        ref = ma.get(chave) or mb[chave]
        linhas.append(
            LinhaComparacao(
                chave=chave,
                rotulo=ref.rotulo or chave,
                unidade=ref.unidade,
                a=ma[chave].valor if chave in ma else None,
                b=mb[chave].valor if chave in mb else None,
            )
        )
    return Comparacao(a, b, linhas)
