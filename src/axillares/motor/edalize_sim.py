"""Simulação e testes pelo Edalize (fluxo `sim`), dentro da imagem fixada.

- `sim`: testbench clássico em Verilog/SystemVerilog, Icarus ou Verilator; passa se o testbench
  terminar com $finish, falha num $fatal ou num erro de compilação. Serve para OLHAR a onda.
- `teste`: testes cocotb (Python) com Icarus; o resultado de cada caso vem do results.xml
  (JUnit), não do código de saída — o Edalize 0.6.8 diz "ok" mesmo com testes falhando.

Fixtures reais em tests/fixtures/{simulacao,cocotb,ondas}/.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from axillares.core.modelos import (
    Artefato,
    CasoTeste,
    Etapa,
    Falha,
    Local,
    Metrica,
    Situacao,
    SituacaoCaso,
    TipoArtefato,
)
from axillares.core.verificacao import ARQUIVO_CASOS
from axillares.motor import junit
from axillares.motor.base import Contexto, ErroMotor

SCRIPT = Path(__file__).parent / "conteiner" / "executar_sim.py"
NO_CONTEINER_PROJETO = "/projeto"
NO_CONTEINER_TRABALHO = "/trabalho"
EXTENSOES_HDL = {".v", ".sv"}
EXTENSOES_ONDA = {".vcd", ".fst"}

# "@@axil:passo <id>" vem do script; "running modulo.teste (1/3)" vem do cocotb
_PASSO = re.compile(r"^@@axil:passo (?P<id>[\w-]+)")
_RODANDO = re.compile(
    r"cocotb\.regression\s+running (?:\S+\.)?(?P<nome>\w+) \((?P<i>\d+)/(?P<n>\d+)\)"
)
_ROTULOS = {"sim-compilar": "compilação", "sim-rodar": "simulação", "teste-rodar": "testes"}
# erros com lugar — Icarus: "/projeto/rtl/x.v:12: syntax error";
# Verilator: "%Error: /projeto/rtl/x.v:3:5: …"
_LUGAR = re.compile(
    r"^(?:%(?P<nivel>Error|Warning)[-\w]*:\s*)?/projeto/(?P<arq>[^:\s]+):(?P<linha>\d+):"
    r"(?:(?P<col>\d+):)?\s*(?P<msg>.*)$"
)
_FATAL = re.compile(r"^(?:FATAL|ERROR|Error):\s*/projeto/(?P<arq>[^:\s]+):(?P<linha>\d+)")
_LIMITE = re.compile(r"^@@axil:limite (?P<s>[\d.]+)")


def descrever_progresso(linha: str) -> str | None:
    achado = _PASSO.match(linha)
    if achado and achado["id"] in _ROTULOS:
        return f"{_ROTULOS[achado['id']]} · {achado['id']}"
    achado = _RODANDO.search(linha)
    if achado:
        return f"teste {achado['i']}/{achado['n']}: {achado['nome']} · teste-rodar"
    return None


def preparar(ctx: Contexto) -> dict:
    """Escreve o pedido para o script da imagem; devolve-o (para testes)."""
    projeto = ctx.projeto
    sim = projeto.simulacao
    rtl = projeto.arquivos_rtl()

    def entrada(arquivo: Path) -> dict:
        tipo = "systemVerilogSource" if arquivo.suffix in {".sv", ".svh"} else "verilogSource"
        return {"name": f"{NO_CONTEINER_PROJETO}/{projeto.relativo(arquivo)}", "file_type": tipo}

    if ctx.etapa is Etapa.SIMULACAO:
        tbs = [a for a in projeto.arquivos_testbench() if a.suffix in EXTENSOES_HDL]
        if not tbs:
            raise ErroMotor(
                "Este projeto não tem testbench em Verilog. Crie um com “axil arquivo "
                f"tb/tb_{projeto.projeto.topo}.v --testbench” (ou pelo botão + Arquivo) e confira "
                "fontes.testbenches no axil.toml."
            )
        topo = projeto.testbench_classico()
        if not any(a.stem == topo for a in tbs):
            nomes = ", ".join(a.stem for a in tbs)
            raise ErroMotor(
                f"Não achei o testbench {topo}: os arquivos de testbench são {nomes}. Cada "
                "arquivo deve ter o nome do módulo; ou diga qual é em [simulacao] testbench = "
                '"nome" no axil.toml.'
            )
        arquivos = [entrada(a) for a in dict.fromkeys([*rtl, *tbs])]
        pedido = {"modo": "classico", "simulador": sim.simulador.value, "topo": topo,
                  "passo_rodar": "sim-rodar"}  # fmt: skip
    elif ctx.etapa is Etapa.TESTE:
        testes = projeto.arquivos_teste()
        if not testes:
            raise ErroMotor(
                f"Nenhum teste cocotb casa com {sim.testes}. Escreva um tb/test_<nome>.py com "
                "funções @cocotb.test() — o modelo contador traz um exemplo."
            )
        pastas = sorted({f"{NO_CONTEINER_PROJETO}/{projeto.relativo(t.parent)}".rstrip("/.")
                         for t in testes})  # fmt: skip
        pedido = {
            "modo": "cocotb", "simulador": "icarus", "topo": projeto.projeto.topo,
            "modulos": ",".join(t.stem for t in testes), "pythonpath": pastas,
            "filtro": ctx.opcoes.get("filtro"), "passo_rodar": "teste-rodar",
        }  # fmt: skip
        arquivos = [entrada(a) for a in rtl]
    else:
        raise ErroMotor(f"A simulação não executa a etapa “{ctx.etapa}”.")

    pedido.update(
        nome=projeto.nome.replace("-", "_"),
        arquivos=arquivos,
        timescale=sim.timescale.replace(" ", ""),
        limite_s=sim.limite_s,
        build=f"{NO_CONTEINER_TRABALHO}/build",
    )
    ctx.dir_trabalho.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT, ctx.dir_trabalho / SCRIPT.name)
    (ctx.dir_trabalho / "pedido.json").write_text(json.dumps(pedido, indent=2), "utf-8")
    return pedido


def _build(ctx: Contexto) -> Path:
    return ctx.dir_trabalho / "build"


def casos(ctx: Contexto) -> list[CasoTeste] | None:
    resultados = _build(ctx) / "results.xml"
    if not resultados.is_file():
        return None
    return junit.ler(resultados.read_text(encoding="utf-8"))


def situacao(ctx: Contexto, codigo_ok: bool) -> Situacao:
    if ctx.etapa is not Etapa.TESTE:
        return Situacao.SUCESSO if codigo_ok else Situacao.FALHA
    lista = casos(ctx)
    if not lista:
        return Situacao.FALHA
    falhou = any(c.situacao is SituacaoCaso.FALHOU for c in lista)
    return Situacao.FALHA if falhou else Situacao.SUCESSO


def coletar_artefatos(ctx: Contexto) -> list[Artefato]:
    build = _build(ctx)
    ctx.dir_saida.mkdir(parents=True, exist_ok=True)
    saida: list[Artefato] = []

    def guardar(origem: Path, tipo: TipoArtefato) -> None:
        destino = ctx.dir_saida / origem.name
        if origem != destino:
            shutil.copy2(origem, destino)
        saida.append(Artefato(nome=origem.name, tipo=tipo, caminho=Path("saida") / origem.name,
                              bytes=destino.stat().st_size))  # fmt: skip

    for onda in sorted(build.glob("*")):
        if onda.suffix in EXTENSOES_ONDA and onda.is_file():
            guardar(onda, TipoArtefato.ONDA)
    lista = casos(ctx)
    if lista is not None:
        guardar(build / "results.xml", TipoArtefato.RELATORIO)
        arquivo = ctx.dir_saida / ARQUIVO_CASOS
        arquivo.write_text(
            json.dumps([c.model_dump(mode="json") for c in lista], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        guardar(arquivo, TipoArtefato.RELATORIO)
    return saida


def coletar_metricas(ctx: Contexto) -> list[Metrica]:
    lista = casos(ctx)
    return junit.metricas(lista) if lista is not None else []


def explicar_falha(ctx: Contexto, linhas: list[str]) -> Falha:
    limite = next((m for m in map(_LIMITE.match, linhas) if m), None)
    if limite:
        return Falha(
            resumo=f"A simulação passou de {float(limite['s']):g} s sem terminar.",
            passo="simulação",
            proximo_passo="O testbench termina com $finish? Sem ele a simulação não para. Se o "
            "teste é longo de propósito, aumente [simulacao] limite_s no axil.toml.",
        )
    lista = casos(ctx) if ctx.etapa is Etapa.TESTE else None
    if lista:
        falhos = [c for c in lista if c.situacao is SituacaoCaso.FALHOU]
        if falhos:
            primeiro = falhos[0]
            return Falha(
                resumo=f"{len(falhos)} de {len(lista)} teste(s) falharam: "
                f"{primeiro.nome} — {primeiro.mensagem}",
                passo="testes",
                mensagens=[f"{c.nome}: {c.mensagem}" for c in falhos[:10]],
                proximo_passo="Abra o caso para ver o valor encontrado e o esperado; a onda da "
                "execução mostra o instante da falha.",
                locais=[
                    Local(
                        arquivo=c.arquivo,
                        linha=c.linha,
                        mensagem=c.mensagem or c.nome,
                        origem="cocotb",
                    )
                    for c in falhos
                    if c.arquivo and c.linha
                ],
            )
    locais: list[Local] = []
    mensagens: list[str] = []
    anterior = ""
    for linha in linhas:
        texto = linha.strip()
        fatal = _FATAL.match(texto)
        if fatal:
            explicacao = anterior or "o testbench chamou $fatal"
            mensagens.append(explicacao)
            locais.append(Local(arquivo=fatal["arq"], linha=int(fatal["linha"]),
                                mensagem=explicacao, origem="simulação"))  # fmt: skip
            continue
        lugar = _LUGAR.match(texto)
        if lugar and lugar["msg"]:
            aviso = lugar["nivel"] == "Warning" or lugar["msg"].lower().startswith("warning")
            mensagens.append(f"{lugar['arq']}:{lugar['linha']}: {lugar['msg']}")
            locais.append(
                Local(
                    arquivo=lugar["arq"],
                    linha=int(lugar["linha"]),
                    coluna=int(lugar["col"] or 1),
                    mensagem=lugar["msg"],
                    gravidade="aviso" if aviso else "erro",
                    origem="simulação",
                )
            )
        if texto and not texto.startswith(("@@axil", "make", "Entering", "Leaving")):
            anterior = texto
    erros = [x for x in locais if x.gravidade == "erro"]
    if ctx.etapa is Etapa.TESTE and lista is None and not erros:
        return Falha(
            resumo="Os testes não chegaram a rodar (o cocotb não gravou resultados).",
            passo="testes",
            mensagens=mensagens[:10],
            proximo_passo="Veja o log: um erro no Python do teste (import, nome do sinal) "
            "impede a regressão de começar.",
        )
    compilou = any(_PASSO.match(x) and "rodar" in x for x in linhas)
    return Falha(
        resumo="O testbench parou num $fatal: a verificação dele falhou."
        if any(_FATAL.match(x.strip()) for x in linhas)
        else ("A simulação falhou." if compilou else "A compilação para simular falhou."),
        passo="simulação" if compilou else "compilação",
        mensagens=mensagens[:10],
        proximo_passo="Os erros com arquivo e linha já estão marcados no editor; o log completo "
        "fica em log.txt na execução.",
        locais=erros[:20],
    )
