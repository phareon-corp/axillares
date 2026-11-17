"""Esquemático pelo Yosys, pelo KLayout e pelo Graphviz da imagem fixada.

- O Yosys lê o Verilog (ou a netlist .vg que a síntese do fluxo deixou) e escreve a netlist em
  JSON (`write_json`). Aqui ela é traduzida para o modelo de core/esquema.py: um bloco por célula,
  um terminal por porta do módulo, uma ligação por par (pino que dirige, pino que recebe).
- No nível de células, o KLayout lê o SPICE da biblioteca do PDK e lista os transistores de cada
  célula usada.
- O Graphviz (`dot -Tjson`) dá a posição de cada bloco e os pontos de passagem de cada fio; o fio
  em ângulo reto é traçado por core.esquema.rotear.

Os resultados brutos ficam em .axil/cache/esquema/ com a chave do conteúdo: abrir de novo a mesma
RTL não sobe contêiner. Fixtures reais em tests/fixtures/esquema/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from axillares.ambiente import complementos as comp
from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core.caderno import Caderno, ErroCaderno, RegistroExecucao
from axillares.core.esquema import (
    Bloco,
    CelulaTransistores,
    Circuito,
    Esquema,
    Ligacao,
    Nivel,
    Origem,
    Pino,
    PortaModulo,
    Transistor,
    classificar,
    dimensionar,
    esquema_de_transistores,
    rotular_redes,
)
from axillares.core.modelos import Etapa, Situacao, TipoArtefato
from axillares.core.projeto import Projeto
from axillares.core.simulacao_esquema import (
    Estimulo,
    LinhaDoTempo,
    de_onda,
    gerar_testbench,
)
from axillares.motor.base import ErroMotor
from axillares.motor.elk import aplicar_elk, grafo_elk

SCRIPT = Path(__file__).parent / "conteiner" / "executar_esquema.py"
SCRIPT_ELK = Path(__file__).parent / "conteiner" / "layout_elk.js"
NO_CONTEINER_PROJETO = "/projeto"
NO_CONTEINER_TRABALHO = "/trabalho"
CACHE = Path(".axil") / "cache" / "esquema"
LIMITE_BLOCOS = 900
"""Acima disto o desenho fica ilegível (e o Graphviz, lento): fica só o inventário."""
LIMITE_FIOS = 4
"""Uma rede com mais destinos que isto vira rótulos de rede em vez de fios."""

# "/projeto/rtl/q.v:2: ERROR: syntax error, unexpected ';'" (tests/fixtures/esquema/)
_ERRO_YOSYS = re.compile(r"^(?P<antes>.*?)ERROR:\s*(?P<msg>.*)$", re.MULTILINE)
_LUGAR_YOSYS = re.compile(r"/projeto/(?P<arq>[^:\s]+):(?P<linha>\d+)")
_SRC = re.compile(r"^/projeto/(?P<arq>[^:|]+):(?P<linha>\d+)")
_RELOGIOS = {"CLK", "CLK_N", "GATE", "GATE_N", "CK", "CLKN", "GCLK", "C"}
_RESETS = {"ARST", "SRST", "R", "S", "RESET_B", "SET_B", "RN", "SN", "RB", "SB", "CLR", "PRE",
           "SET", "RESET", "AD", "ALOAD", "SETN", "RESETN"}  # fmt: skip
# pinos de alimentação ficam implícitos no esquemático de portas e de células, como no papel
PINOS_ALIMENTACAO = {"VPWR", "VGND", "VPB", "VNB", "VDD", "VSS", "VNW", "VPW", "VCC", "GND"}
_SELECAO = {"S", "S0", "S1", "S2", "S3", "SEL"}


class Netlist:
    """Saída bruta de uma extração (o que vai para o cache)."""

    def __init__(
        self, yosys: dict, transistores: dict | None = None, verilog: str = "", vg: str = "",
        pdk: str = "",
    ) -> None:  # fmt: skip
        self.yosys = yosys
        self.transistores = transistores or {}
        self.verilog = verilog
        """A mesma netlist em Verilog (RTL e portas): é o que se simula."""
        self.vg = vg
        """No nível de células: a .vg da execução, relativa ao projeto."""
        self.pdk = pdk


# --- de onde vem a netlist de células ---------------------------------------------------------


def execucao_com_netlist(projeto: Projeto) -> tuple[RegistroExecucao, Path] | None:
    """A execução ASIC bem-sucedida mais recente que deixou a netlist de células (.vg).

    Prefere uma da RTL atual; se não houver, a mais recente de qualquer RTL.
    """
    try:
        caderno = Caderno(projeto.dir_runs)
        registros = [r for r in caderno.listar() if r.etapa in (Etapa.SINTESE, Etapa.GDS)
                     and r.situacao is Situacao.SUCESSO]  # fmt: skip
    except (ErroCaderno, OSError):
        return None
    atual = projeto.hash_rtl()
    registros.sort(key=lambda r: (r.hash_rtl != atual, -r.inicio.timestamp()))
    for r in registros:
        try:
            completo = caderno.carregar(r.id)
        except ErroCaderno:
            continue
        for a in completo.artefatos:
            caminho = (completo.diretorio or Path()) / a.caminho
            if a.tipo is TipoArtefato.NETLIST and caminho.suffix == ".vg" and caminho.is_file():
                completo.numero = r.numero
                return completo, caminho
    return None


# --- tradução da netlist do Yosys -------------------------------------------------------------


def _inteiro(binario: str | int) -> int | None:
    if isinstance(binario, int):
        return binario
    try:
        return int(binario, 2)
    except (TypeError, ValueError):
        return None


def _origem(atributos: dict) -> Origem | None:
    achado = _SRC.match(str(atributos.get("src", "")))
    if not achado or achado["arq"].startswith("runs/"):
        return None
    return Origem(achado["arq"], int(achado["linha"]))


def _ordem_entrada(simbolo: str):
    def chave(nome: str) -> int:
        if simbolo in {"registrador", "latch"}:
            if nome.upper() in _RELOGIOS:
                return 2
            if nome.upper() in _RESETS:
                return 3
            return 0 if nome.upper().startswith("D") else 1
        return 0

    return chave


def _lado(simbolo: str, nome: str, direcao: str) -> str:
    if direcao == "saida":
        return "e"
    if simbolo == "mux" and nome.upper() in _SELECAO:
        return "s"
    return "w"


def _constante(bits: list[str]) -> str:
    if len(bits) == 1:
        return {"0": "0", "1": "1"}.get(bits[0], bits[0].upper())
    if all(b in "01" for b in bits):
        valor = int("".join(reversed(bits)), 2)
        return f"{len(bits)}'h{valor:X}"
    return f"{len(bits)}'b" + "".join(reversed(bits)).upper()


def _nome_da_rede(bits: list[int], nomes: dict[int, tuple[str, int, int]]) -> str:
    """'q' se os bits são a rede inteira; 'q[3]' para um bit; 'q[7:4]' para uma fatia."""
    if not bits or bits[0] not in nomes:
        return ""
    rede, _, largura = nomes[bits[0]]
    if largura == 1:
        return rede
    indices = [nomes[b][1] for b in bits if b in nomes and nomes[b][0] == rede]
    if len(indices) == largura:
        return rede
    if len(indices) == 1:
        return f"{rede}[{indices[0]}]"
    return f"{rede}[{max(indices)}:{min(indices)}]"


def traduzir_modulo(nome: str, modulo: dict, nivel: Nivel) -> Esquema:
    """Um módulo do JSON do Yosys como Esquema (sem posições)."""
    esq = Esquema(nome=nome, nivel=nivel)
    motorista: dict[int, tuple[str, str]] = {}
    receptores: list[tuple[str, str, list]] = []
    nomes: dict[int, tuple[str, int, int]] = {}
    """bit → (rede, índice, largura da rede)"""
    for rede, dados in sorted(modulo.get("netnames", {}).items(), key=lambda x: x[1]["hide_name"]):
        for bit in dados["bits"]:
            if isinstance(bit, int) and bit not in nomes:
                nomes[bit] = (rede, dados["bits"].index(bit), len(dados["bits"]))

    for porta, dados in modulo.get("ports", {}).items():
        if porta.upper() in PINOS_ALIMENTACAO:
            continue
        direcao = {"input": "entrada", "output": "saida"}.get(dados["direction"], "bidir")
        lado = "e" if direcao != "saida" else "w"
        explicacao = {"entrada": "Entrada do módulo.", "saida": "Saída do módulo."}.get(
            direcao, "Pino bidirecional do módulo."
        )
        todos = dados["bits"]
        # no RTL, um barramento é um terminal só; em portas e células, cada bit é um fio próprio
        if nivel is Nivel.RTL or len(todos) == 1:
            partes = [(porta, porta if len(todos) == 1 else f"{porta}[{len(todos) - 1}:0]", todos)]
        else:
            partes = [(f"{porta}[{i}]", f"{porta}[{i}]", [bit]) for i, bit in enumerate(todos)]
        for nome_pino, rotulo, bits in partes:
            ident = f"porta:{nome_pino}"
            b = Bloco(id=ident, simbolo=direcao, rotulo=rotulo, tipo="porta", instancia=porta,
                      pinos=[Pino(nome_pino, direcao, lado, len(bits), bits=list(bits))],
                      largura_bits=len(bits), explicacao=explicacao)  # fmt: skip
            esq.blocos.append(b)
            if direcao == "saida":
                receptores.append((ident, nome_pino, bits))
            else:
                for bit in bits:
                    if isinstance(bit, int):
                        motorista.setdefault(bit, (ident, nome_pino))

    for i, (inst, celula) in enumerate(modulo.get("cells", {}).items()):
        classe = classificar(celula["type"])
        if classe.simbolo == "fisica":
            esq.fisicas[celula["type"]] = esq.fisicas.get(celula["type"], 0) + 1
            continue
        direcoes = celula.get("port_directions", {})
        conexoes = celula.get("connections", {})
        conexoes = {p: b for p, b in conexoes.items() if p.upper() not in PINOS_ALIMENTACAO}
        entradas = [p for p in conexoes if direcoes.get(p, "input") == "input"]
        entradas.sort(key=_ordem_entrada(classe.simbolo))
        saidas = [p for p in conexoes if direcoes.get(p) == "output"]
        params = celula.get("parameters", {})
        largura = _inteiro(params.get("WIDTH", "")) or max(
            (len(conexoes[p]) for p in saidas), default=1
        )
        detalhes = {}
        if not celula.get("hide_name"):
            detalhes["instância"] = inst
        for chave in ("WIDTH", "A_WIDTH", "B_WIDTH", "Y_WIDTH", "S_WIDTH"):
            if chave in params and (v := _inteiro(params[chave])) is not None:
                detalhes[chave.lower().replace("_", " ")] = str(v)
        if "ARST_VALUE" in params:
            detalhes["valor no reset"] = str(_inteiro(params["ARST_VALUE"]))
        for chave, texto in (("CLK_POLARITY", "borda"), ("ARST_POLARITY", "reset ativo em"),
                             ("EN_POLARITY", "habilitação ativa em")):  # fmt: skip
            if chave in params:
                v = _inteiro(params[chave])
                detalhes[texto] = ("subida" if v else "descida") if chave == "CLK_POLARITY" \
                    else ("1" if v else "0")  # fmt: skip
        ident = f"c{i}"
        b = Bloco(
            id=ident, simbolo=classe.simbolo, rotulo=classe.rotulo, tipo=celula["type"],
            instancia="" if celula.get("hide_name") else inst,
            pinos=[Pino(p, "entrada", _lado(classe.simbolo, p, "entrada"), len(conexoes[p]),
                        bits=list(conexoes[p])) for p in entradas]
            + [Pino(p, "saida", "e", len(conexoes[p]), bits=list(conexoes[p])) for p in saidas],
            largura_bits=largura, detalhes=detalhes, explicacao=classe.texto,
            origem=_origem(celula.get("attributes", {})),
        )  # fmt: skip
        esq.blocos.append(b)
        for p in saidas:
            for bit in conexoes[p]:
                if isinstance(bit, int):
                    motorista.setdefault(bit, (ident, p))
        for p in entradas:
            receptores.append((ident, p, conexoes[p]))

    constantes = 0
    for ident, pino, bits in receptores:
        grupos: dict[tuple[str, str], list[int]] = {}
        fixos: list[str] = []
        for bit in bits:
            if isinstance(bit, str):
                fixos.append(bit)
            elif bit in motorista and motorista[bit] != (ident, pino):
                grupos.setdefault(motorista[bit], []).append(bit)
        if fixos:
            constantes += 1
            valor = _constante(fixos)
            k = Bloco(id=f"k{constantes}", simbolo="constante", rotulo=valor, tipo="constante",
                      pinos=[Pino("Y", "saida", "e", len(fixos), bits=list(fixos))],
                      explicacao="Valor fixo: na síntese vira uma ligação ao terra (0) ou ao VDD "
                      "(1), ou some.")  # fmt: skip
            esq.blocos.append(k)
            esq.ligacoes.append(Ligacao((k.id, "Y"), (ident, pino), valor, len(fixos),
                                        bits=list(fixos)))  # fmt: skip
        for origem, lista in grupos.items():
            esq.ligacoes.append(Ligacao(origem, (ident, pino), _nome_da_rede(lista, nomes),
                                        len(lista), bits=lista))  # fmt: skip
    direcoes = {"input": "entrada", "output": "saida"}
    esq.portas = [
        PortaModulo(porta, direcoes.get(d["direction"], "bidir"), len(d["bits"]))
        for porta, d in modulo.get("ports", {}).items()
    ]
    esq.redes = {rede: list(dados["bits"]) for rede, dados in modulo.get("netnames", {}).items()}
    rotular_redes(esq, LIMITE_FIOS)
    for b in esq.blocos:
        dimensionar(b)
    return esq


def _um(valor: float) -> float:
    """Largura/comprimento em µm: o SPICE do sky130 usa .option scale=1e-6 (valor já em µm);
    os outros PDKs escrevem em metros."""
    return valor * 1e6 if 0 < valor < 1e-3 else valor


def traduzir_transistores(dados: dict, netlist: dict) -> dict[str, CelulaTransistores]:
    direcoes: dict[str, dict[str, str]] = {}
    for modulo in netlist.get("modules", {}).values():
        for celula in modulo.get("cells", {}).values():
            direcoes.setdefault(celula["type"], celula.get("port_directions", {}))
    saida = {}
    for tipo, cel in dados.items():
        d = {k: v for k, v in direcoes.get(tipo, {}).items() if k.upper() not in PINOS_ALIMENTACAO}
        transistores = [
            Transistor(
                nome=t["nome"], modelo=t["modelo"].lower(),
                dreno=t["terminais"].get("D", ""), porta=t["terminais"].get("G", ""),
                fonte=t["terminais"].get("S", ""), corpo=t["terminais"].get("B", ""),
                w_um=round(_um(t["w"]), 4), l_um=round(_um(t["l"]), 4),
            )
            for t in cel["dispositivos"]
        ]  # fmt: skip
        saida[tipo] = CelulaTransistores(
            tipo=tipo, pinos=cel["pinos"], transistores=transistores,
            entradas=frozenset(p for p in cel["pinos"] if d.get(p) == "input"),
            saidas=frozenset(p for p in cel["pinos"] if d.get(p) == "output"),
        )  # fmt: skip
    return saida


def traduzir(netlist: Netlist, nivel: Nivel, topo: str) -> Circuito:
    circ = Circuito(nivel=nivel, topo=topo)
    marcado = None
    for nome, modulo in netlist.yosys.get("modules", {}).items():
        circ.modulos[nome] = traduzir_modulo(nome, modulo, nivel)
        if _inteiro(modulo.get("attributes", {}).get("top", "0")):
            marcado = nome
    if circ.topo not in circ.modulos:
        circ.topo = marcado or next(iter(circ.modulos), topo)
    circ.celulas = traduzir_transistores(netlist.transistores, netlist.yosys)
    circ.verilog = netlist.verilog
    circ.vg = netlist.vg
    circ.pdk = netlist.pdk
    return circ


# --- execução na imagem -----------------------------------------------------------------------


def _chave(*partes: str | bytes) -> str:
    h = hashlib.sha256()
    for p in partes:
        h.update(p if isinstance(p, bytes) else p.encode())
        h.update(b"\0")
    return h.hexdigest()[:20]


Progresso = Callable[[str], None]
ROTULOS = {
    "esquema-rtl": "Yosys lendo o RTL",
    "esquema-portas": "Yosys sintetizando em portas",
    "esquema-celulas": "Yosys lendo a netlist de células",
    "esquema-transistores": "KLayout lendo os transistores das células",
    "esquema-posicoes": "ELK montando o desenho",
    "esquema-simular": "Icarus simulando o circuito",
}


class GeradorEsquema:
    def __init__(
        self,
        perfil: Perfil | None = None,
        executor: Executor | None = None,
        programa: ct.ProgramaConteiner | None = None,
    ) -> None:
        self.perfil = perfil or carregar_perfil()
        self.executor = executor or ExecutorReal()
        self._programa = programa

    def programa(self) -> ct.ProgramaConteiner:
        if self._programa is None:
            self._programa = ct.detectar_programa(self.executor)
        if self._programa is None:
            raise ErroMotor("Nem podman nem docker instalados; veja “axil ambiente situacao”.")
        return self._programa

    def comando(
        self,
        projeto: Projeto,
        trabalho: Path,
        programa: list[str] | None = None,
        montagens: list[str] | None = None,
    ) -> list[str]:
        prog = self.programa()
        usuario = (
            ["--userns=keep-id"] if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )  # fmt: skip
        caminhos = ":".join([*self.perfil.imagem.caminhos, "/usr/local/bin", "/usr/bin", "/bin"])
        bibliotecas = ":".join(self.perfil.imagem.bibliotecas)
        programa = programa or [
            "python3", f"{NO_CONTEINER_TRABALHO}/{SCRIPT.name}",
            f"{NO_CONTEINER_TRABALHO}/pedido.json",
        ]  # fmt: skip
        extra = [x for m in montagens or [] for x in ("-v", m)]
        return [
            prog.nome, "run", "--rm", "--init", "--network=none", *usuario,
            "-v", f"{projeto.raiz}:{NO_CONTEINER_PROJETO}:ro,z",
            "-v", f"{trabalho}:{NO_CONTEINER_TRABALHO}:z", *extra,
            "-e", "HOME=/tmp", "-e", f"PATH={caminhos}", "-e", f"LD_LIBRARY_PATH={bibliotecas}",
            "-w", NO_CONTEINER_TRABALHO, "--entrypoint", programa[0],
            self.perfil.imagem.referencia, *programa[1:],
        ]  # fmt: skip

    def _rodar(
        self,
        projeto: Projeto,
        pedido: dict | None,
        ao_progresso: Progresso | None,
        arquivos: dict[str, str] | None = None,
        programa: list[str] | None = None,
        montagens: list[str] | None = None,
        explicar=None,
    ) -> Path:
        """Roda na imagem com uma pasta de trabalho nova; devolve a pasta de saída dela."""
        trabalho = Path(tempfile.mkdtemp(prefix="axil-esquema-"))
        (trabalho / "saida").mkdir()
        shutil.copy2(SCRIPT, trabalho / SCRIPT.name)
        shutil.copy2(SCRIPT_ELK, trabalho / SCRIPT_ELK.name)
        for nome, conteudo in (arquivos or {}).items():
            (trabalho / nome).write_text(conteudo, encoding="utf-8")
        if pedido is not None:
            pedido = {**pedido, "saida": f"{NO_CONTEINER_TRABALHO}/saida"}
            (trabalho / "pedido.json").write_text(json.dumps(pedido), encoding="utf-8")

        ultimo: list[str] = []

        def receber(linha: str) -> None:
            if ao_progresso and linha.startswith("@@axil:passo "):
                texto = ROTULOS.get(linha.split()[1], linha.split()[1])
                if ultimo != [texto]:
                    ultimo[:] = [texto]
                    ao_progresso(texto)

        comando = self.comando(projeto, trabalho, programa, montagens)
        resultado = self.executor.transmitir(comando, receber)
        if not resultado.ok:
            shutil.rmtree(trabalho, ignore_errors=True)
            raise ErroMotor((explicar or explicar_erro)(resultado.saida))
        return trabalho / "saida"

    def _cache(self, projeto: Projeto) -> Path:
        pasta = projeto.raiz / CACHE
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    def netlist(
        self, projeto: Projeto, nivel: Nivel, ao_progresso: Progresso | None = None
    ) -> tuple[Netlist, str]:
        """A netlist bruta do nível e de onde ela veio (texto para o usuário)."""
        if nivel is Nivel.TRANSISTORES:
            nivel = Nivel.CELULAS
        topo = projeto.projeto.topo
        pedido: dict = {"modo": "netlist", "nivel": nivel.value, "topo": topo}
        vg_rel = pdk = ""
        if nivel is Nivel.CELULAS:
            achada = execucao_com_netlist(projeto)
            if achada is None:
                raise ErroMotor(
                    "Ainda não há netlist de células: rode a síntese (Executar ▸ síntese) e "
                    "volte aqui — o esquemático das células mostra o que a síntese montou."
                )
            registro, vg = achada
            pdk = registro.pdk or projeto.asic.pdk.value
            liberty = self.perfil.celulas_lib.get(pdk)
            if liberty is None:
                raise ErroMotor(f"O perfil não sabe onde está a biblioteca de células do {pdk}.")
            vg_rel = projeto.relativo(vg)
            pedido |= {"netlist": f"{NO_CONTEINER_PROJETO}/{vg_rel}",
                       "liberty": liberty, "spice": self.perfil.celulas_spice.get(pdk)}  # fmt: skip
            chave = _chave(nivel.value, pdk, vg.read_bytes())
            atual = registro.hash_rtl == projeto.hash_rtl()
            origem = f"netlist da execução #{registro.numero} ({registro.etapa.value})" + (
                "" if atual else " — de uma RTL anterior; rode a síntese para atualizar"
            )
        else:
            arquivos = projeto.arquivos_rtl()
            if not arquivos:
                raise ErroMotor("O projeto não tem fontes RTL; confira fontes.rtl no axil.toml.")
            pedido["arquivos"] = [f"{NO_CONTEINER_PROJETO}/{projeto.relativo(a)}"
                                  for a in arquivos]  # fmt: skip
            chave = _chave(nivel.value, topo, projeto.hash_rtl())
            origem = "fontes do projeto"
        arquivo = self._cache(projeto) / f"netlist-{chave}.json"
        if arquivo.is_file():
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        else:
            saida = self._rodar(projeto, pedido, ao_progresso)
            try:
                t = saida / "transistores.json"
                v = saida / "netlist.v"
                dados = {
                    "yosys": json.loads((saida / "netlist.json").read_text(encoding="utf-8")),
                    "transistores": json.loads(t.read_text("utf-8")) if t.is_file() else {},
                    "verilog": v.read_text("utf-8") if v.is_file() else "",
                }
            finally:
                shutil.rmtree(saida.parent, ignore_errors=True)
            arquivo.write_text(json.dumps(dados), "utf-8")
        bruta = Netlist(dados["yosys"], dados.get("transistores"), dados.get("verilog", ""),
                        vg_rel, pdk)  # fmt: skip
        return bruta, origem

    def _elk(self, ao_progresso: Progresso | None) -> Path:
        nome = "elkjs"
        complemento = self.perfil.complementos.get(nome)
        if complemento is None:
            raise ErroMotor("O perfil de ferramentas não declara o elkjs (complementos.elkjs).")
        try:
            return comp.garantir(nome, complemento, ao_progresso)
        except comp.ErroComplemento as erro:
            raise ErroMotor(str(erro)) from erro

    def posicionar(
        self, projeto: Projeto, esquemas: list[Esquema], ao_progresso: Progresso | None = None
    ) -> None:
        grafos = {str(i): grafo_elk(esq) for i, esq in enumerate(esquemas)
                  if len(esq.blocos) <= LIMITE_BLOCOS}  # fmt: skip
        if not grafos:
            return
        texto = json.dumps(grafos, sort_keys=True)
        chave = _chave("elk", self.perfil.complementos["elkjs"].versao, texto)
        arquivo = self._cache(projeto) / f"posicoes-{chave}.json"
        if arquivo.is_file():
            posicoes = json.loads(arquivo.read_text(encoding="utf-8"))
        else:
            pasta_elk = self._elk(ao_progresso)
            elk = Path(self.perfil.complementos["elkjs"].arquivo).name
            saida = self._rodar(
                projeto, None, ao_progresso, arquivos={"grafos.json": texto},
                programa=["node", f"{NO_CONTEINER_TRABALHO}/{SCRIPT_ELK.name}", f"/elk/{elk}",
                          f"{NO_CONTEINER_TRABALHO}/grafos.json",
                          f"{NO_CONTEINER_TRABALHO}/saida/posicoes.json"],
                montagens=[f"{pasta_elk}:/elk:ro,z"],
            )  # fmt: skip
            try:
                posicoes = json.loads((saida / "posicoes.json").read_text(encoding="utf-8"))
            finally:
                shutil.rmtree(saida.parent, ignore_errors=True)
            arquivo.write_text(json.dumps(posicoes), encoding="utf-8")
        for i, esq in enumerate(esquemas):
            if str(i) in posicoes:
                aplicar_elk(esq, posicoes[str(i)])

    def gerar(
        self, projeto: Projeto, nivel: Nivel, ao_progresso: Progresso | None = None
    ) -> Circuito:
        """Extrai, traduz e posiciona: o circuito pronto para desenhar."""
        bruta, origem = self.netlist(projeto, nivel, ao_progresso)
        circ = traduzir(bruta, Nivel.CELULAS if nivel is Nivel.TRANSISTORES else nivel,
                        projeto.projeto.topo)  # fmt: skip
        circ.origem = origem
        esquemas = list(circ.modulos.values())
        for tipo, cel in sorted(circ.celulas.items()):
            if not cel.transistores:  # fill, tap: sem transistor nenhum
                continue
            esq = esquema_de_transistores(cel)
            circ.esquemas_celulas[tipo] = esq
            esquemas.append(esq)
        self.posicionar(projeto, esquemas, ao_progresso)
        return circ

    # --- simulação ---------------------------------------------------------------------------

    def simular(
        self,
        projeto: Projeto,
        circ: Circuito,
        estimulo: Estimulo,
        ao_progresso: Progresso | None = None,
    ) -> LinhaDoTempo:
        """Simula o circuito desenhado com o estímulo e devolve o valor de cada fio no tempo."""
        esq = circ.modulos[circ.topo]
        tb = gerar_testbench(circ.topo, esq.portas, estimulo, "sim.vcd")
        defines: list[str] = []
        arquivos_txt = {"tb.v": tb}
        if circ.vg:
            modelos = self.perfil.celulas_verilog.get(circ.pdk)
            if not modelos:
                raise ErroMotor(
                    f"O perfil não traz os modelos de simulação das células do {circ.pdk}; "
                    "simule nos níveis RTL ou portas."
                )
            defines = list(self.perfil.celulas_verilog_defines.get(circ.pdk, []))
            if any(p.alimentacao for p in esq.portas):
                defines.append("USE_POWER_PINS")
            fontes = [*modelos, f"{NO_CONTEINER_PROJETO}/{circ.vg}"]
            chave_netlist = circ.vg + _chave((projeto.raiz / circ.vg).read_bytes())
        else:
            if not circ.verilog:
                raise ErroMotor("Gere o esquemático de novo (↻) para poder simular.")
            arquivos_txt["netlist.v"] = circ.verilog
            fontes = [f"{NO_CONTEINER_TRABALHO}/netlist.v"]
            chave_netlist = circ.verilog
        chave = _chave("sim", chave_netlist, tb, " ".join(defines))
        onda = self._cache(projeto) / f"sim-{chave}.vcd"
        if not onda.is_file():
            pedido = {"modo": "simular", "tb": f"{NO_CONTEINER_TRABALHO}/tb.v",
                      "arquivos": fontes, "defines": defines,
                      "limite_s": projeto.simulacao.limite_s}  # fmt: skip
            saida = self._rodar(projeto, pedido, ao_progresso, arquivos=arquivos_txt,
                                explicar=explicar_erro_simulacao)  # fmt: skip
            try:
                gravada = saida / "sim.vcd"
                if not gravada.is_file():
                    raise ErroMotor("O Icarus terminou sem gravar a onda da simulação.")
                shutil.move(str(gravada), onda)
            finally:
                shutil.rmtree(saida.parent, ignore_errors=True)
        return linha_do_tempo(onda, esq, estimulo)


def linha_do_tempo(onda: Path, esq: Esquema, estimulo: Estimulo) -> LinhaDoTempo:
    """Lê a onda (pywellen, motor/ondas.py) e reparte cada sinal da netlist pelos seus bits."""
    from axillares.motor.ondas import ErroOnda, Onda

    try:
        o = Onda(onda)
    except ErroOnda as erro:
        raise ErroMotor(str(erro)) from erro
    sinais = {s.nome_completo: s for s in o.sinais}
    por_bit: dict[int, list[tuple[float, str]]] = {}
    for rede, bits in esq.redes.items():
        if not any(isinstance(b, int) and b not in por_bit for b in bits):
            continue
        nome = next((n for n in (f"axil_tb.dut.{rede}", f"axil_tb.dut.\\{rede}")
                     if n in sinais), None)  # fmt: skip
        if nome is None:
            continue
        largura = len(bits)
        trocas = [(o.em_ps(t) / 1000.0, de_onda(v, largura)) for t, v in o.mudancas(nome)]
        for i, bit in enumerate(bits):
            if not isinstance(bit, int) or bit in por_bit:
                continue
            lista: list[tuple[float, str]] = []
            for t, texto in trocas:
                c = texto[largura - 1 - i]
                if not lista or lista[-1][1] != c:
                    lista.append((t, c))
            por_bit[bit] = lista
    return LinhaDoTempo(estimulo, por_bit)


def explicar_erro_simulacao(saida: str) -> str:
    limite = re.search(r"@@axil:limite (\S+)", saida)
    if limite:
        return (f"A simulação passou de {limite[1]} s sem terminar. Diminua o número de ciclos "
                "ou aumente [simulacao] limite_s no axil.toml.")  # fmt: skip
    ultimas = "\n".join(x for x in saida.strip().splitlines()[-8:] if not x.startswith("@@"))
    return f"O Icarus não conseguiu simular o circuito desenhado.\n{ultimas}".strip()


def explicar_erro(saida: str) -> str:
    achados = list(_ERRO_YOSYS.finditer(saida))
    erros = [m["msg"].strip() for m in achados]
    if erros:
        lugar = _LUGAR_YOSYS.search(achados[0]["antes"] + erros[0])
        onde = f" ({lugar['arq']}, linha {lugar['linha']})" if lugar else ""
        return (
            f"O Yosys não conseguiu ler o circuito{onde}: {erros[0]}\n"
            "Corrija o erro no editor (o lint ao salvar aponta a linha) e gere o esquemático "
            "de novo."
        )
    ultimas = "\n".join(saida.strip().splitlines()[-6:])
    return f"Não consegui gerar o esquemático.\n{ultimas}".strip()


__all__ = [
    "Bloco",
    "GeradorEsquema",
    "Netlist",
    "execucao_com_netlist",
    "linha_do_tempo",
    "traduzir",
    "traduzir_modulo",
]
