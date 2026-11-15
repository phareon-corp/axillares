"""Leitura de ondas (VCD e FST) pelo pywellen — a mesma biblioteca de leitura do Surfer.

O Axillares não lê VCD/FST à mão: o pywellen entrega a hierarquia e as mudanças de
cada sinal; aqui só se dá forma ao que a interface desenha. Fixtures reais em
tests/fixtures/ondas/ (Icarus FST, Verilator VCD, cocotb FST, e uma com X e Z).

Valores: inteiros quando todos os bits são 0/1; texto de bits ("1x0z") quando há X ou Z.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FATORES_PS = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "us": 1e6, "ms": 1e9, "s": 1e12}


class ErroOnda(Exception):
    """Mensagem pronta para o usuário."""


@dataclass(frozen=True)
class SinalOnda:
    nome_completo: str
    nome: str
    escopo: str
    largura: int
    tipo: str

    @property
    def profundidade(self) -> int:
        return self.escopo.count(".") + (1 if self.escopo else 0)


Valor = int | str


class Onda:
    def __init__(self, caminho: Path) -> None:
        try:
            import pywellen
        except ImportError as erro:  # pragma: no cover - depende da instalação
            raise ErroOnda(
                "Para ver ondas dentro do app falta o pacote pywellen: "
                "pip install 'axillares[gui]'."
            ) from erro
        if not caminho.is_file():
            raise ErroOnda(f"A onda {caminho.name} não existe.")
        try:
            self._w = pywellen.Waveform(str(caminho))
        except Exception as erro:
            raise ErroOnda(f"Não consegui ler a onda {caminho.name}: {erro}") from erro
        self.caminho = caminho
        self.formato = str(self._w.file_format)
        escala = self._w.timescale
        self.fator = int(escala.factor) if escala else 1
        self.unidade = str(escala.unit) if escala else "ps"
        self._vars = {}
        self.sinais: list[SinalOnda] = []
        for v in self._w.all_vars():
            completo = v.full_name
            escopo, _, nome = completo.rpartition(".")
            self._vars[completo] = v
            self.sinais.append(
                SinalOnda(completo, nome, escopo, int(v.bitwidth or 1), str(v.var_type))
            )
        self._cache: dict[str, list[tuple[int, Valor]]] = {}
        self._fim: int | None = None

    def mudancas(self, nome_completo: str) -> list[tuple[int, Valor]]:
        """(tempo, valor) em ordem; o tempo está em unidades da escala da onda."""
        if nome_completo not in self._cache:
            v = self._vars.get(nome_completo)
            if v is None:
                raise ErroOnda(f"O sinal {nome_completo} não está nesta onda.")
            self._cache[nome_completo] = [(int(t), _valor(x)) for t, x in v.tv]
        return self._cache[nome_completo]

    def valor_em(self, nome_completo: str, tempo: int) -> Valor | None:
        lista = self.mudancas(nome_completo)
        # busca binária pela última mudança <= tempo
        baixo, alto = 0, len(lista)
        while baixo < alto:
            meio = (baixo + alto) // 2
            if lista[meio][0] <= tempo:
                baixo = meio + 1
            else:
                alto = meio
        return lista[baixo - 1][1] if baixo else None

    @property
    def fim(self) -> int:
        """O último instante com mudança em qualquer sinal."""
        if self._fim is None:
            self._fim = max((self.mudancas(s.nome_completo)[-1][0] for s in self.sinais
                             if self.mudancas(s.nome_completo)), default=0)  # fmt: skip
        return self._fim

    def em_ps(self, tempo: int) -> float:
        return tempo * self.fator * FATORES_PS.get(self.unidade, 1.0)

    def escopos(self) -> list[str]:
        return list(dict.fromkeys(s.escopo for s in self.sinais))

    def sinais_iniciais(self, limite: int = 12) -> list[str]:
        """O que mostrar ao abrir: os sinais do escopo de cima (as portas do testbench ou do
        circuito), sem parâmetros constantes."""
        if not self.sinais:
            return []
        raso = min(s.profundidade for s in self.sinais)
        escolhidos = [s for s in self.sinais
                      if s.profundidade == raso and s.tipo != "Parameter"]  # fmt: skip
        return [s.nome_completo for s in escolhidos[:limite]]


def _valor(x: object) -> Valor:
    if isinstance(x, int):
        return x
    texto = str(x).strip("'\" ").lower()
    if texto and set(texto) <= {"0", "1"}:
        return int(texto, 2)
    return texto


def formatar(valor: Valor | None, largura: int, base: str = "hex") -> str:
    """Como o valor aparece na onda: 1 bit em 0/1; barramentos em hex, decimal ou binário."""
    if valor is None:
        return "?"
    if isinstance(valor, str):
        if set(valor) <= {"x"}:
            return "x"
        if set(valor) <= {"z"}:
            return "z"
        return valor
    if largura == 1:
        return str(valor)
    if base == "dec":
        return str(valor)
    if base == "bin":
        return format(valor, f"0{largura}b")
    return format(valor, f"0{(largura + 3) // 4}x")


def desconhecido(valor: Valor | None) -> str | None:
    """'x', 'z' ou None — para colorir o trecho."""
    if isinstance(valor, str):
        return "z" if "z" in valor and "x" not in valor else "x"
    return None
