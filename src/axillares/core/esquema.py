"""Esquemático: o circuito em notação técnica, no vocabulário do Axillares.

Quem lê o Verilog é o Yosys, quem lê o SPICE das células é o KLayout e quem calcula as posições é
o Graphviz — tudo em motor/esquema.py. Aqui mora só o modelo (blocos com símbolo, pinos,
ligações), a geometria de cada símbolo (onde fica cada pino), a classificação de cada tipo de
célula num símbolo (dado, em templates/explicacoes/esquema.toml), o desenho em ângulos retos dos
fios a partir dos pontos de passagem do Graphviz e o inventário "o que há no chip".

Níveis: RTL (operadores como o código descreve), portas lógicas genéricas, células do PDK e,
dentro de cada célula, transistores.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise

from axillares.core import explicacoes as ex


class Nivel(StrEnum):
    RTL = "rtl"
    PORTAS = "portas"
    CELULAS = "celulas"
    TRANSISTORES = "transistores"

    @property
    def titulo(self) -> str:
        return {
            Nivel.RTL: "RTL",
            Nivel.PORTAS: "Portas lógicas",
            Nivel.CELULAS: "Células do PDK",
            Nivel.TRANSISTORES: "Transistores",
        }[self]


# Símbolos que o visor sabe desenhar. Portas têm a forma IEEE "distintiva".
PORTAS = {"and", "nand", "or", "nor", "xor", "xnor", "not", "buf", "tribuf"}
CAIXAS = {"registrador", "latch", "memoria", "celula", "modulo", "complexa", "somador_completo",
          "operador", "comparador", "deslocador"}  # fmt: skip
TERMINAIS = {"entrada", "saida", "bidir"}
ALIMENTACAO = {"vdd", "gnd"}
TRANSISTORES = {"nmos", "pmos"}

REDES_VDD = {"VPWR", "VDD", "VCC", "VDDI"}
REDES_GND = {"VGND", "VSS", "GND", "VSSI"}

ALIMENTACAO_ALTA = REDES_VDD | {"VPB", "VNW"}
ALIMENTACAO_BAIXA = REDES_GND | {"VNB", "VPW"}

ESTOCADA = 10.0
"""Quanto o fio sai reto de um pino antes de dobrar."""


@dataclass(frozen=True)
class PortaModulo:
    """Uma porta do módulo, inclusive as de alimentação (que não aparecem no desenho)."""

    nome: str
    direcao: str  # entrada · saida · bidir
    largura: int

    @property
    def alimentacao(self) -> str | None:
        """'1' ou '0' se é pino de alimentação (VDD, VSS, VPWR…), senão None."""
        nome = self.nome.upper()
        if nome in ALIMENTACAO_ALTA:
            return "1"
        if nome in ALIMENTACAO_BAIXA:
            return "0"
        return None


@dataclass
class Pino:
    nome: str
    direcao: str  # "entrada" · "saida" · "bidir"
    lado: str = "w"  # w · e · n · s · c (centro: junção)
    largura: int = 1
    x: float = 0.0
    y: float = 0.0
    """Relativos ao canto superior esquerdo do bloco."""
    rede_externa: str = ""
    """Nome escrito junto do pino em vez de um fio (entradas da célula nos transistores)."""
    bits: list = field(default_factory=list)
    """Bits da netlist ligados ao pino (inteiros do Yosys ou constantes "0"/"1"), LSB primeiro."""


@dataclass
class Origem:
    arquivo: str
    linha: int


@dataclass
class Bloco:
    id: str
    simbolo: str
    rotulo: str
    tipo: str
    """O nome original: "$add", "$_NAND_", "sky130_fd_sc_hd__nand2_1", "pfet_01v8"."""
    instancia: str = ""
    pinos: list[Pino] = field(default_factory=list)
    largura_bits: int = 1
    detalhes: dict[str, str] = field(default_factory=dict)
    explicacao: str = ""
    origem: Origem | None = None
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    def pino(self, nome: str) -> Pino:
        return next(p for p in self.pinos if p.nome == nome)

    def ponto(self, nome: str) -> tuple[float, float]:
        p = self.pino(nome)
        return self.x + p.x, self.y + p.y


@dataclass
class Ligacao:
    de: tuple[str, str]
    para: tuple[str, str]
    rede: str = ""
    largura: int = 1
    pontos: list[tuple[float, float]] = field(default_factory=list)
    restringe: bool = True
    """Se conta para a ordem das colunas (Graphviz `constraint`)."""
    bits: list = field(default_factory=list)
    """Bits da netlist que o fio carrega — é por eles que a simulação acha o valor."""


@dataclass
class Esquema:
    nome: str
    nivel: Nivel
    blocos: list[Bloco] = field(default_factory=list)
    ligacoes: list[Ligacao] = field(default_factory=list)
    orientacao: str = "LR"
    largura: float = 0.0
    altura: float = 0.0
    juncoes: list[tuple[float, float]] = field(default_factory=list)
    posicionado: bool = False
    portas: list[PortaModulo] = field(default_factory=list)
    redes: dict[str, list] = field(default_factory=dict)
    """Nome de cada rede da netlist → seus bits (para casar com os sinais da simulação)."""
    fisicas: dict[str, int] = field(default_factory=dict)
    """Células físicas (fill, tap, decap…) que existem no chip mas não entram no desenho."""

    def bloco(self, ident: str) -> Bloco:
        return self._indice()[ident]

    def _indice(self) -> dict[str, Bloco]:
        if getattr(self, "_cache", None) is None or len(self._cache) != len(self.blocos):
            self._cache = {b.id: b for b in self.blocos}
        return self._cache

    def componentes(self) -> list[Bloco]:
        """Os blocos que são componentes do circuito (sem terminais, junções e trilhos)."""
        fora = TERMINAIS | ALIMENTACAO | {"juncao", "constante", "rotulo"}
        return [b for b in self.blocos if b.simbolo not in fora]


# --- classificação (dado) --------------------------------------------------------------------


@dataclass(frozen=True)
class Classe:
    simbolo: str
    rotulo: str = ""
    texto: str = ""


_PREFIXO_BIBLIOTECA = re.compile(r"^(?:sky130_\w+?__|gf180mcu_\w+?__|sg13g2_)")
_FORCA = re.compile(r"_(\d+)$")


def familia_da_celula(tipo: str) -> str:
    """'sky130_fd_sc_hd__a21oi_1' → 'a21oi'; 'sg13g2_nand2_1' → 'nand2'."""
    return _FORCA.sub("", _PREFIXO_BIBLIOTECA.sub("", tipo))


def eh_celula_de_biblioteca(tipo: str) -> bool:
    return bool(_PREFIXO_BIBLIOTECA.match(tipo))


def classificar(tipo: str) -> Classe:
    """O símbolo, o rótulo e a explicação de um tipo de célula (Yosys ou PDK)."""
    dados = ex.esquema()
    if tipo.startswith("$"):
        entrada = dados["yosys"].get(tipo)
        if entrada is None:
            entrada = next(
                (e for padrao, e in dados["padroes_yosys"].items() if re.match(padrao, tipo)),
                None,
            )
        if entrada is None:
            return Classe("celula", tipo.lstrip("$"), "Operação interna do Yosys.")
        return Classe(entrada["simbolo"], entrada.get("rotulo", ""), entrada.get("texto", ""))
    if not eh_celula_de_biblioteca(tipo):
        return Classe("modulo", tipo, "Instância de outro módulo do projeto.")
    familia = familia_da_celula(tipo)
    simbolo = next(
        (s for padrao, s in dados["familias"].items() if re.match(padrao, familia)), "celula"
    )
    sabido = ex.celula(tipo)
    texto = sabido[0] if sabido else dados["simbolos"].get(simbolo, "")
    return Classe(simbolo, familia, texto)


# --- geometria --------------------------------------------------------------------------------


def _distribuir(n: int, comprimento: float) -> list[float]:
    passo = comprimento / (n + 1)
    return [passo * (i + 1) for i in range(n)]


def dimensionar(b: Bloco) -> None:
    """Tamanho do bloco e posição de cada pino, conforme o símbolo."""
    oeste = [p for p in b.pinos if p.lado == "w"]
    leste = [p for p in b.pinos if p.lado == "e"]
    sul = [p for p in b.pinos if p.lado == "s"]
    norte = [p for p in b.pinos if p.lado == "n"]
    n = max(len(oeste), len(leste), 1)
    s = b.simbolo
    if s in TERMINAIS:
        w, h = 58.0, 18.0
    elif s in ALIMENTACAO:
        w, h = 24.0, 22.0
    elif s == "constante":
        w, h = max(28.0, 7.0 * len(b.rotulo) + 12), 18.0
    elif s == "juncao":
        w, h = 4.0, 4.0
    elif s in TRANSISTORES:
        rotulo = max((len(p.rede_externa) for p in b.pinos), default=0)
        w, h = 40.0 + (6.5 * (rotulo + 2) + 8 if rotulo else 0), 48.0  # + "=1" na simulação
    elif s == "rotulo":
        w, h = 7.0 * len(b.rotulo) + 18, 14.0
    elif s in {"not", "buf", "tribuf"}:
        w, h = 44.0, 32.0
    elif s in PORTAS:
        w, h = 52.0, max(40.0, 14.0 * (n + 1))
    elif s == "mux":
        w, h = 40.0, max(56.0, 18.0 * (n + 1))
    elif s in {"operador", "comparador", "deslocador"}:
        w, h = 52.0, max(48.0, 18.0 * (n + 1))
    elif s in {"registrador", "latch"}:
        w, h = 64.0, max(64.0, 18.0 * (n + 1))
    else:  # caixas com nomes de pinos: célula, módulo, complexa…
        maior = max((len(p.nome) for p in b.pinos), default=1)
        w = max(84.0, 7.0 * len(b.rotulo) + 24, 2 * 7.0 * maior + 36)
        h = max(48.0, 18.0 * (n + 1))
    b.w, b.h = w, h

    if s == "juncao":
        for p in b.pinos:
            p.x, p.y = w / 2, h / 2
        return
    if s in TRANSISTORES:
        canal = w - 12
        for p in b.pinos:
            p.x, p.y = {"w": (0.0, h / 2), "n": (canal, 0.0), "s": (canal, h)}[p.lado]
        return
    if s in ALIMENTACAO:
        for p in b.pinos:
            p.x, p.y = w / 2, (h if s == "vdd" else 0.0)
        return
    # portas de 1 entrada e terminais: o pino no meio
    for p, y in zip(oeste, _distribuir(len(oeste), h), strict=True):
        p.x, p.y = 0.0, y
    for p, y in zip(leste, _distribuir(len(leste), h), strict=True):
        p.x, p.y = w, y
    for p, x in zip(sul, _distribuir(len(sul), w), strict=True):
        p.x, p.y = x, h
    for p, x in zip(norte, _distribuir(len(norte), w), strict=True):
        p.x, p.y = x, 0.0


def rotular_redes(esq: Esquema, limite: int = 4) -> None:
    """Redes com muitos destinos (relógio, reset, habilitação) viram rótulos de rede: cada destino
    ganha uma etiqueta com o nome, em vez de um fio atravessando o desenho — como no papel."""
    por_origem: dict[tuple[str, str], list[Ligacao]] = {}
    for lig in esq.ligacoes:
        por_origem.setdefault(lig.de, []).append(lig)
    novos: list[Bloco] = []
    for origem, ligs in por_origem.items():
        if len(ligs) <= limite:
            continue
        motorista = esq.bloco(origem[0])
        nome = motorista.rotulo if motorista.simbolo in TERMINAIS else (ligs[0].rede or origem[1])
        if motorista.simbolo in TERMINAIS and ":" in nome:  # "q[7:0]" → "q"; "q[3]" fica
            nome = nome.split("[")[0]
        for lig in ligs:
            esq.ligacoes.remove(lig)
            etiqueta = Bloco(id=f"r{len(novos)}", simbolo="rotulo", rotulo=nome, tipo="rotulo",
                             pinos=[Pino("x", "saida", "e", lig.largura)],
                             explicacao=f"Rótulo de rede: ligado a “{nome}”.")  # fmt: skip
            novos.append(etiqueta)
            esq.ligacoes.append(Ligacao((etiqueta.id, "x"), lig.para, lig.rede, lig.largura,
                                        bits=lig.bits))  # fmt: skip
        if motorista.simbolo not in TERMINAIS:
            fonte = Bloco(id=f"r{len(novos)}", simbolo="rotulo", rotulo=nome, tipo="rotulo",
                          pinos=[Pino("x", "entrada", "w", ligs[0].largura)],
                          explicacao=f"Rótulo de rede: a rede “{nome}” sai daqui.")  # fmt: skip
            novos.append(fonte)
            esq.ligacoes.append(Ligacao(origem, (fonte.id, "x"), ligs[0].rede, ligs[0].largura,
                                        bits=ligs[0].bits))  # fmt: skip
    esq.blocos.extend(novos)


# --- fios em ângulo reto ----------------------------------------------------------------------

_DIRECOES = {"w": (-1, 0), "e": (1, 0), "n": (0, -1), "s": (0, 1), "c": (0, 0)}


def _estocada(ponto: tuple[float, float], lado: str) -> tuple[float, float]:
    dx, dy = _DIRECOES.get(lado, (0, 0))
    return ponto[0] + dx * ESTOCADA, ponto[1] + dy * ESTOCADA


def rotear(
    inicio: tuple[float, float],
    lado_inicio: str,
    fim: tuple[float, float],
    lado_fim: str,
    passagem: list[tuple[float, float]],
    orientacao: str = "LR",
) -> list[tuple[float, float]]:
    """Fio em ângulos retos do pino `inicio` ao pino `fim`, passando perto dos pontos do Graphviz.

    Cada trecho entre dois pontos vira horizontal–vertical–horizontal (LR) ou
    vertical–horizontal–vertical (TB), com a dobra no meio — no canal entre colunas de blocos.
    """
    pontos = [inicio, _estocada(inicio, lado_inicio), *passagem, _estocada(fim, lado_fim), fim]
    saida = [pontos[0]]
    for b in pontos[1:]:
        a = saida[-1]
        if abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5:
            saida.append(b)
            continue
        if orientacao == "LR":
            meio = (a[0] + b[0]) / 2
            saida += [(meio, a[1]), (meio, b[1]), b]
        else:
            meio = (a[1] + b[1]) / 2
            saida += [(a[0], meio), (b[0], meio), b]
    return _simplificar(saida)


def _simplificar(pontos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Tira pontos repetidos e pontos no meio de um trecho reto."""
    limpo: list[tuple[float, float]] = []
    for p in pontos:
        if limpo and abs(limpo[-1][0] - p[0]) < 0.01 and abs(limpo[-1][1] - p[1]) < 0.01:
            continue
        limpo.append(p)
    i = 1
    while i < len(limpo) - 1:
        a, b, c = limpo[i - 1], limpo[i], limpo[i + 1]
        colinear = (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or (
            abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01
        )
        if colinear:
            del limpo[i]
        else:
            i += 1
    return limpo


def _sobre(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    eps = 0.5
    if abs(a[0] - b[0]) < eps and abs(p[0] - a[0]) < eps:
        return min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    if abs(a[1] - b[1]) < eps and abs(p[1] - a[1]) < eps:
        return min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
    return False


def calcular_juncoes(esquema: Esquema) -> None:
    """Pontos onde um fio se divide em dois (mesma origem): ganham uma bolinha, como no papel."""
    por_origem: dict[tuple[str, str], list[list[tuple[float, float]]]] = {}
    for lig in esquema.ligacoes:
        if len(lig.pontos) >= 2:
            por_origem.setdefault(lig.de, []).append(lig.pontos)
    juncoes: set[tuple[float, float]] = set()
    for caminhos in por_origem.values():
        if len(caminhos) < 2:
            continue
        for i, caminho in enumerate(caminhos):
            for p in caminho[1:-1]:
                for j, outro in enumerate(caminhos):
                    if i == j:
                        continue
                    toca = any(_sobre(p, a, b) for a, b in pairwise(outro))
                    if toca:
                        juncoes.add((round(p[0], 1), round(p[1], 1)))
                        break
    for b in esquema.blocos:
        if b.simbolo == "juncao":
            grau = sum(1 for lig in esquema.ligacoes if b.id in (lig.de[0], lig.para[0]))
            if grau >= 3:
                juncoes.add((round(b.x + b.w / 2, 1), round(b.y + b.h / 2, 1)))
    esquema.juncoes = sorted(juncoes)


# --- transistores de uma célula --------------------------------------------------------------


@dataclass(frozen=True)
class Transistor:
    nome: str
    modelo: str
    dreno: str
    porta: str
    fonte: str
    corpo: str
    w_um: float
    l_um: float

    @property
    def canal_p(self) -> bool:
        m = self.modelo.lower()
        return "pfet" in m or "pmos" in m or m.endswith("_p") or "pch" in m


@dataclass(frozen=True)
class CelulaTransistores:
    tipo: str
    pinos: list[str]
    transistores: list[Transistor]
    entradas: frozenset[str] = frozenset()
    saidas: frozenset[str] = frozenset()

    @property
    def n_pmos(self) -> int:
        return sum(1 for t in self.transistores if t.canal_p)

    @property
    def n_nmos(self) -> int:
        return len(self.transistores) - self.n_pmos


def _distancias(origens: set[str], arestas: dict[str, set[str]]) -> dict[str, int]:
    dist = {o: 0 for o in origens}
    fila = deque(origens)
    while fila:
        rede = fila.popleft()
        for vizinha in arestas.get(rede, ()):
            if vizinha not in dist:
                dist[vizinha] = dist[rede] + 1
                fila.append(vizinha)
    return dist


def esquema_de_transistores(cel: CelulaTransistores) -> Esquema:
    """Uma célula como rede de transistores: pMOS em cima (puxam para VDD), nMOS embaixo."""
    esq = Esquema(nome=cel.tipo, nivel=Nivel.TRANSISTORES, orientacao="TB")
    vdd = {r for r in cel.pinos if r.upper() in REDES_VDD}
    gnd = {r for r in cel.pinos if r.upper() in REDES_GND}
    canais: dict[str, set[str]] = {}
    for t in cel.transistores:
        canais.setdefault(t.dreno, set()).add(t.fonte)
        canais.setdefault(t.fonte, set()).add(t.dreno)
    d_vdd = _distancias(vdd, canais)
    d_gnd = _distancias(gnd, canais)
    infinito = 10**6

    # usos de cada rede: (bloco, pino, papel) — papel "cima" = rede acima do transistor
    usos: dict[str, list[tuple[str, str, str]]] = {}
    for i, t in enumerate(cel.transistores):
        ident = f"t{i}"
        a, b = t.dreno, t.fonte

        def chave(rede: str) -> tuple[int, int]:
            return (d_vdd.get(rede, infinito), -d_gnd.get(rede, infinito))

        cima, baixo = (a, b) if chave(a) <= chave(b) else (b, a)
        # o MOS é simétrico: por convenção, a fonte do pMOS fica no lado do VDD e a do nMOS no
        # lado do terra (o SPICE extraído do layout nem sempre os nomeia assim)
        papel_cima = "S" if t.canal_p else "D"
        papel_baixo = "D" if t.canal_p else "S"
        simbolo = "pmos" if t.canal_p else "nmos"
        esq.blocos.append(
            Bloco(
                id=ident, simbolo=simbolo, rotulo=t.nome, tipo=t.modelo, instancia=t.nome,
                pinos=[Pino("G", "entrada", "w"), Pino(papel_cima, "bidir", "n"),
                       Pino(papel_baixo, "bidir", "s")],
                detalhes={"W": f"{t.w_um:g} µm", "L": f"{t.l_um:g} µm", "porta": t.porta,
                          "dreno": t.dreno, "fonte": t.fonte, "corpo": t.corpo},
                explicacao=(
                    "Transistor pMOS: conduz quando a porta está em 0 e liga a saída ao VDD."
                    if t.canal_p else
                    "Transistor nMOS: conduz quando a porta está em 1 e liga a saída ao terra."
                ),
            )
        )  # fmt: skip
        usos.setdefault(cima, []).append((ident, papel_cima, "cima"))
        usos.setdefault(baixo, []).append((ident, papel_baixo, "baixo"))
        usos.setdefault(t.porta, []).append((ident, "G", "porta"))

    contador = 0
    for rede, lista in usos.items():
        if rede in vdd or rede in gnd:
            sim = "vdd" if rede in vdd else "gnd"
            for ident, pino, papel in lista:
                contador += 1
                lado = "s" if sim == "vdd" else "n"
                trilho = Bloco(id=f"a{contador}", simbolo=sim, rotulo=rede, tipo=rede,
                               pinos=[Pino("x", "bidir", lado)])  # fmt: skip
                esq.blocos.append(trilho)
                if sim == "vdd":
                    esq.ligacoes.append(Ligacao((trilho.id, "x"), (ident, pino), rede,
                                                restringe=papel != "porta"))  # fmt: skip
                else:
                    esq.ligacoes.append(Ligacao((ident, pino), (trilho.id, "x"), rede,
                                                restringe=papel != "porta"))  # fmt: skip
            continue
        acima = [(i, p) for i, p, papel in lista if papel == "baixo"]  # rede abaixo do transistor
        abaixo = [(i, p) for i, p, papel in lista if papel == "cima"]
        portas = [(i, p) for i, p, papel in lista if papel == "porta"]
        entrada = rede in cel.pinos and rede not in cel.saidas
        if entrada:
            # entradas da célula: o nome escrito junto de cada porta, como nos livros
            for ident, pino in portas:
                esq.bloco(ident).pino(pino).rede_externa = rede
            portas = []
        canal = acima + abaixo
        if not canal and not portas:
            continue
        if rede not in cel.pinos and len(canal) + len(portas) == 2:
            # dois usos dentro da célula: um fio direto
            if acima and abaixo:
                esq.ligacoes.append(Ligacao(acima[0], abaixo[0], rede))
            elif portas and canal:
                esq.ligacoes.append(Ligacao(canal[0], portas[0], rede, restringe=False))
            else:
                a, b = (canal + portas)[:2]
                esq.ligacoes.append(Ligacao(a, b, rede, restringe=False))
            continue
        contador += 1
        juncao = Bloco(id=f"j{contador}", simbolo="juncao", rotulo=rede, tipo="rede",
                       pinos=[Pino("x", "bidir", "c")])  # fmt: skip
        if rede in cel.pinos:
            juncao.detalhes["pino"] = "saida" if rede in cel.saidas else "entrada"
        esq.blocos.append(juncao)
        no = (juncao.id, "x")
        for origem in acima:
            esq.ligacoes.append(Ligacao(origem, no, rede))
        for destino in abaixo:
            esq.ligacoes.append(Ligacao(no, destino, rede))
        for destino in portas:
            esq.ligacoes.append(Ligacao(no, destino, rede, restringe=False))
    for b in esq.blocos:
        dimensionar(b)
    return esq


# --- inventário -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemInventario:
    tipo: str
    simbolo: str
    rotulo: str
    quantidade: int
    explicacao: str
    transistores: int | None = None
    """Transistores de UMA instância (nível de células)."""


@dataclass
class Circuito:
    """O resultado de uma extração: os módulos num nível e, nas células, os transistores."""

    nivel: Nivel
    topo: str
    modulos: dict[str, Esquema] = field(default_factory=dict)
    celulas: dict[str, CelulaTransistores] = field(default_factory=dict)
    esquemas_celulas: dict[str, Esquema] = field(default_factory=dict)
    """Cada célula usada desenhada como rede de transistores."""
    origem: str = ""
    """De onde veio: "fontes do projeto" ou o nome da execução de síntese."""
    verilog: str = ""
    """A netlist em Verilog (RTL e portas) — é o que se simula."""
    vg: str = ""
    """No nível de células: a .vg da execução, relativa ao projeto (simulada com os modelos)."""
    pdk: str = ""

    def inventario(self, modulo: str | None = None) -> list[ItemInventario]:
        esq = self.modulos[modulo or self.topo]
        contagem = Counter(b.tipo for b in esq.componentes())
        exemplo = {b.tipo: b for b in esq.componentes()}
        itens = []
        for tipo, n in contagem.most_common():
            b = exemplo[tipo]
            cel = self.celulas.get(tipo)
            itens.append(ItemInventario(tipo, b.simbolo, b.rotulo, n, b.explicacao,
                                        len(cel.transistores) if cel else None))  # fmt: skip
        for tipo, n in sorted(esq.fisicas.items(), key=lambda x: -x[1]):
            classe = classificar(tipo)
            cel = self.celulas.get(tipo)
            itens.append(ItemInventario(tipo, "fisica", classe.rotulo, n, classe.texto,
                                        len(cel.transistores) if cel else None))  # fmt: skip
        return itens

    def transistores(self, modulo: str | None = None) -> tuple[int, int] | None:
        """(pMOS, nMOS) do módulo inteiro; None fora do nível de células."""
        if not self.celulas:
            return None
        esq = self.modulos[modulo or self.topo]
        p = n = 0
        tipos = Counter(b.tipo for b in esq.componentes()) + Counter(esq.fisicas)
        for tipo, quantos in tipos.items():
            cel = self.celulas.get(tipo)
            if cel:
                p += cel.n_pmos * quantos
                n += cel.n_nmos * quantos
        return p, n

    def transistores_fisicos(self, modulo: str | None = None) -> int:
        """Quantos dos transistores estão em células físicas (decap, fillcap)."""
        esq = self.modulos[modulo or self.topo]
        return sum(
            len(self.celulas[tipo].transistores) * n
            for tipo, n in esq.fisicas.items()
            if tipo in self.celulas
        )

    def bits_de_registro(self, modulo: str | None = None) -> int:
        return sum(
            b.largura_bits
            for b in self.modulos[modulo or self.topo].componentes()
            if b.simbolo == "registrador"
        )
