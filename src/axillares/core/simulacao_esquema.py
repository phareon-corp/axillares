"""O esquemático em funcionamento: estímulo, testbench, linha do tempo e estado dos transistores.

Quem simula é o Icarus Verilog da imagem (motor/esquema.py). Aqui só:
  - o estímulo que a pessoa monta (o valor de cada entrada a cada ciclo, o relógio e o período);
  - o testbench em Verilog gerado a partir dele (texto, como os modelos de arquivo);
  - a linha do tempo de cada bit da netlist, para pintar os fios no instante escolhido;
  - nos transistores, quais conduzem: um pMOS conduz com a porta em 0, um nMOS com a porta em 1,
    e cada nó vale o que estiver ligado a ele por transistores conduzindo. É uma ilustração lógica
    a partir dos valores que o Icarus calculou nos pinos da célula — não é simulação elétrica.

Convenção de tempo: o ciclo k ocupa [k·T, (k+1)·T); o relógio começa em 0 e sobe no meio do
ciclo (k·T + T/2); as entradas mudam no começo do ciclo, longe da borda de subida.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from axillares.core.esquema import (
    ALIMENTACAO_ALTA,
    ALIMENTACAO_BAIXA,
    CelulaTransistores,
    Esquema,
    PortaModulo,
)

_RELOGIO = re.compile(r"^(clk|clock|ck|clk_i|i_clk|clk_in|sys_clk|clki)$", re.IGNORECASE)
_RESET = re.compile(r"^(rst|reset|arst|srst|clr)(_?n|_?b|_?l|_ni|_i)?$|^n_?(rst|reset)$",
                    re.IGNORECASE)  # fmt: skip
_RESET_BAIXO = re.compile(r"(_?n|_?b|_?l|_ni)$|^n_?", re.IGNORECASE)
_HABILITA = re.compile(r"^(en|ena|enable|ce|habilita|start|go)(_i)?$", re.IGNORECASE)


@dataclass
class Estimulo:
    ciclos: int = 16
    periodo_ns: float = 10.0
    relogio: str | None = None
    entradas: dict[str, dict[int, int]] = field(default_factory=dict)
    """porta → {ciclo: valor a partir daquele ciclo}."""

    def valor(self, porta: str, ciclo: int) -> int:
        eventos = self.entradas.get(porta, {})
        anteriores = [c for c in eventos if c <= ciclo]
        return eventos[max(anteriores)] if anteriores else 0

    def definir(self, porta: str, ciclo: int, valor: int, manter_futuro: bool = False) -> None:
        """A entrada passa a valer `valor` a partir do ciclo; por padrão, esquece o que vinha
        depois (é o que se espera ao mexer numa chave durante a simulação)."""
        eventos = self.entradas.setdefault(porta, {})
        if not manter_futuro:
            for c in [c for c in eventos if c > ciclo]:
                del eventos[c]
        eventos[ciclo] = valor
        # tira eventos que não mudam nada
        anterior = None
        for c in sorted(eventos):
            if eventos[c] == anterior:
                del eventos[c]
            else:
                anterior = eventos[c]

    @property
    def fim_ns(self) -> float:
        return self.ciclos * self.periodo_ns

    def ciclo_em(self, t_ns: float) -> int:
        return max(0, min(self.ciclos - 1, int(t_ns // self.periodo_ns)))


def portas_do_modulo(esq: Esquema) -> list[PortaModulo]:
    return list(esq.portas)


def eh_reset(nome: str) -> bool:
    return bool(_RESET.match(nome))


def reset_ativo_em_baixo(nome: str) -> bool:
    return bool(_RESET_BAIXO.search(nome))


def sugerir_estimulo(esq: Esquema, ciclos: int = 16, periodo_ns: float = 10.0) -> Estimulo:
    """Um estímulo que já mostra o circuito funcionando: relógio achado pelo nome ou por ligar
    no pino de relógio de um registrador, reset ativo nos 2 primeiros ciclos, habilitação em 1."""
    entradas = [p for p in esq.portas if p.direcao == "entrada" and p.alimentacao is None]
    relogio = next((p.nome for p in entradas if p.largura == 1 and _RELOGIO.match(p.nome)), None)
    if relogio is None:
        ligados_a_clk = {
            lig.de[0].removeprefix("porta:")
            for lig in esq.ligacoes
            for b in [esq.bloco(lig.para[0])]
            if b.simbolo in {"registrador", "latch"} and lig.para[1].upper() in {"CLK", "C", "CK"}
            and lig.de[0].startswith("porta:")
        }  # fmt: skip
        relogio = next((p.nome for p in entradas if p.nome in ligados_a_clk), None)
    est = Estimulo(ciclos=ciclos, periodo_ns=periodo_ns, relogio=relogio)
    for p in entradas:
        if p.nome == relogio:
            continue
        if p.largura == 1 and eh_reset(p.nome):
            ativo = 0 if reset_ativo_em_baixo(p.nome) else 1
            est.entradas[p.nome] = {0: ativo, 2: 1 - ativo}
        elif p.largura == 1 and _HABILITA.match(p.nome):
            est.entradas[p.nome] = {0: 0, 2: 1}
        else:
            est.entradas[p.nome] = {0: 0}
    return est


def _literal(valor: int, largura: int) -> str:
    return f"{largura}'d{valor & ((1 << largura) - 1)}"


def _ns(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def gerar_testbench(topo: str, portas: list[PortaModulo], est: Estimulo, onda: str) -> str:
    """Testbench em Verilog: liga o circuito, gera o relógio e aplica as entradas a cada ciclo."""
    linhas = ["// Gerado pelo Axillares (esquemático em funcionamento).", "`timescale 1ns/1ps",
              "module axil_tb;"]  # fmt: skip
    conexoes = []
    for p in portas:
        if p.alimentacao is not None:
            linhas.append(f"  {'supply1' if p.alimentacao == '1' else 'supply0'} {p.nome};")
        elif p.direcao == "entrada":
            faixa = f"[{p.largura - 1}:0] " if p.largura > 1 else ""
            linhas.append(f"  reg {faixa}{p.nome} = {_literal(est.valor(p.nome, 0), p.largura)};")
        else:
            faixa = f"[{p.largura - 1}:0] " if p.largura > 1 else ""
            linhas.append(f"  wire {faixa}{p.nome};")
        conexoes.append(f".{p.nome}({p.nome})")
    linhas.append(f"  {topo} dut ({', '.join(conexoes)});")
    if est.relogio:
        linhas.append(f"  always #({_ns(est.periodo_ns / 2)}) {est.relogio} = ~{est.relogio};")
    linhas += ["  initial begin", f'    $dumpfile("{onda}");', "    $dumpvars(0, axil_tb);"]
    larguras = {p.nome: p.largura for p in portas}
    mudancas: dict[int, list[tuple[str, int]]] = {}
    for porta, eventos in est.entradas.items():
        if porta not in larguras or porta == est.relogio:
            continue
        for ciclo, valor in eventos.items():
            if 0 < ciclo < est.ciclos:
                mudancas.setdefault(ciclo, []).append((porta, valor))
    agora = 0
    for ciclo in sorted(mudancas):
        linhas.append(f"    #({_ns((ciclo - agora) * est.periodo_ns)});")
        for porta, valor in sorted(mudancas[ciclo]):
            linhas.append(f"    {porta} = {_literal(valor, larguras[porta])};")
        agora = ciclo
    linhas.append(f"    #({_ns((est.ciclos - agora) * est.periodo_ns)});")
    linhas += ["    $finish;", "  end", "endmodule", ""]
    return "\n".join(linhas)


# --- linha do tempo -----------------------------------------------------------------------------


class LinhaDoTempo:
    """O valor de cada bit da netlist ao longo do tempo (em ns), lido da onda da simulação."""

    def __init__(self, estimulo: Estimulo, mudancas: dict[int, list[tuple[float, str]]]):
        self.estimulo = estimulo
        self._tempos = {bit: [t for t, _ in lista] for bit, lista in mudancas.items()}
        self._valores = {bit: [v for _, v in lista] for bit, lista in mudancas.items()}

    @property
    def bits(self) -> set[int]:
        return set(self._tempos)

    def bit(self, bit: int | str, t_ns: float) -> str:
        if isinstance(bit, str):
            return bit.lower() if bit.lower() in "01xz" else "x"
        tempos = self._tempos.get(bit)
        if not tempos:
            return "?"
        i = bisect.bisect_right(tempos, t_ns + 1e-9)
        return self._valores[bit][i - 1] if i else "x"

    def valor(self, bits: list, t_ns: float) -> str:
        """Os bits como texto, do mais significativo ao menos ('0101'); '?' se não há sinal."""
        return "".join(self.bit(b, t_ns) for b in reversed(bits))

    def mudou_em(self, bits: list, t0: float, t1: float) -> bool:
        return self.valor(bits, t0) != self.valor(bits, t1)


def formatar(valor: str) -> str:
    """'1' → '1'; '00000101' → '0x05'; com x ou z, o texto binário."""
    if len(valor) <= 1:
        return valor
    if set(valor) <= {"0", "1"}:
        return f"0x{int(valor, 2):0{(len(valor) + 3) // 4}X}"
    if set(valor) == {"?"}:
        return "?"
    return valor


def de_onda(valor: int | str | None, largura: int) -> str:
    """Valor como a onda devolve (inteiro, ou texto com x/z) → texto binário com a largura."""
    if valor is None:
        return "x" * largura
    if isinstance(valor, int):
        return format(valor, f"0{largura}b")[-largura:]
    texto = valor.lower()
    return texto.rjust(largura, texto[0] if texto and texto[0] in "xz" else "0")[-largura:]


# --- transistores ---------------------------------------------------------------------------


def estado_transistores(
    cel: CelulaTransistores, pinos: dict[str, str]
) -> tuple[dict[str, str], dict[str, bool | None]]:
    """Valor de cada nó e se cada transistor conduz, dados os valores nos pinos da célula.

    As entradas e a alimentação são fontes; as saídas que o Icarus calculou também entram como
    fontes no fim, para resolver nós de memória (laços de flip-flops) que dependem do passado.
    """
    fontes: dict[str, str] = {}
    for p in cel.pinos:
        nome = p.upper()
        if nome in ALIMENTACAO_ALTA:
            fontes[p] = "1"
        elif nome in ALIMENTACAO_BAIXA:
            fontes[p] = "0"
        elif p in cel.entradas and pinos.get(p) in {"0", "1"}:
            fontes[p] = pinos[p]
    valores: dict[str, str] = dict(fontes)
    conduz: dict[str, bool | None] = {}

    def resolver(fixas: dict[str, str]) -> None:
        for _ in range(4 * len(cel.transistores) + 4):
            for t in cel.transistores:
                g = valores.get(t.porta, "x")
                conduz[t.nome] = None if g not in "01" else (g == "0") == t.canal_p
            pai: dict[str, str] = {}

            def raiz(n: str, pai: dict[str, str] = pai) -> str:
                while pai.get(n, n) != n:
                    n = pai[n]
                return n

            for t in cel.transistores:
                if conduz[t.nome]:
                    a, b = raiz(t.dreno), raiz(t.fonte)
                    if a != b:
                        pai[a] = b
            grupos: dict[str, set[str]] = {}
            for t in cel.transistores:
                for n in (t.dreno, t.fonte, t.porta):
                    grupos.setdefault(raiz(n), set()).add(n)
            novos = dict(valores)
            for nos in grupos.values():
                fixos = {fixas[n] for n in nos if n in fixas}
                if fixos:
                    v = fixos.pop() if len(fixos) == 1 else "x"
                    for n in nos:
                        if n not in fixas:
                            novos[n] = v
            if novos == valores:
                return
            valores.clear()
            valores.update(novos)

    resolver(fontes)
    saidas = {p: pinos[p] for p in cel.saidas if pinos.get(p) in {"0", "1"}}
    if any(valores.get(p) != v for p, v in saidas.items()):
        resolver({**fontes, **saidas})
    return valores, conduz
