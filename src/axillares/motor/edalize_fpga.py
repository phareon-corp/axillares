"""MotorEdalize (FPGA): Yosys → nextpnr → bitstream pelo Edalize, dentro da imagem fixada.

Como no MotorSiliconCompiler, nada de Edalize é importado aqui: um pedido em JSON vai para o
script que roda na imagem, e o relatório do nextpnr é traduzido em relatorio_nextpnr.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core import placas
from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao, TipoArtefato
from axillares.motor import relatorio_nextpnr
from axillares.motor.base import Contexto, ErroMotor

SCRIPT = Path(__file__).parent / "conteiner" / "executar_edalize.py"
NO_CONTEINER_PROJETO = "/projeto"
NO_CONTEINER_TRABALHO = "/trabalho"
_ERRO = re.compile(r"^(ERROR|Error):?\s*(.+)$")
# linha que o Makefile do Edalize ecoa → "rótulo · id do passo" (ids de explicacoes/fluxo.toml)
_PASSOS = (
    ("yosys ", "síntese para FPGA · fpga-sintese"),
    ("nextpnr-", "posicionamento e roteamento · fpga-pnr"),
    ("icepack ", "bitstream · fpga-bitstream"),
    ("ecppack ", "bitstream · fpga-bitstream"),
)


class MotorEdalize:
    nome = "edalize"

    def __init__(
        self,
        perfil: Perfil | None = None,
        executor: Executor | None = None,
        programa: ct.ProgramaConteiner | None = None,
    ) -> None:
        self.perfil = perfil or carregar_perfil()
        self.executor = executor or ExecutorReal()
        self._programa = programa

    def versao(self) -> str:
        versao = self.perfil.motores.get(self.nome)
        if not versao:
            raise ErroMotor(
                f"O perfil {self.perfil.identificador} não declara a versão do Edalize."
            )
        return versao

    def etapas(self) -> set[Etapa]:
        return {Etapa.FPGA}

    def programa(self) -> ct.ProgramaConteiner:
        if self._programa is None:
            self._programa = ct.detectar_programa(self.executor)
        if self._programa is None:
            raise ErroMotor("Nem podman nem docker instalados; veja “axil ambiente situacao”.")
        return self._programa

    def placa(self, ctx: Contexto) -> placas.Placa:
        ident = ctx.projeto.fpga.placa
        if not ident:
            raise ErroMotor(
                "O projeto não diz qual é a placa FPGA. No axil.toml, seção [fpga], escreva "
                'placa = "icebreaker" (ou "ulx3s") e o mapeamento dos pinos em '
                "[fpga.pinos.<placa>]."
            )
        try:
            return placas.carregar(ident)
        except placas.ErroPlaca as erro:
            raise ErroMotor(str(erro)) from erro

    # --- preparar ---------------------------------------------------------------------------

    def preparar(self, ctx: Contexto) -> list[str]:
        if ctx.etapa is not Etapa.FPGA:
            raise ErroMotor(
                f"O Edalize (neste Axillares) executa só a etapa fpga, não “{ctx.etapa}”."
            )
        placa = self.placa(ctx)
        mapa = ctx.projeto.fpga.pinos.get(placa.id, {})
        if not mapa:
            raise ErroMotor(
                f"Falta o mapeamento de pinos para a placa {placa.nome}: crie "
                f"[fpga.pinos.{placa.id}] no axil.toml, ligando cada porta do módulo a um recurso "
                "da placa (clk, btn0, led0…)."
            )
        try:
            texto = placas.gerar_restricoes(placa, mapa)
        except placas.ErroPlaca as erro:
            raise ErroMotor(str(erro)) from erro
        ctx.dir_trabalho.mkdir(parents=True, exist_ok=True)
        restricoes = ctx.dir_trabalho / f"pinos.{placa.restricoes}"
        restricoes.write_text(texto, encoding="utf-8")
        shutil.copy2(SCRIPT, ctx.dir_trabalho / SCRIPT.name)

        arquivos = []
        for a in ctx.projeto.arquivos_rtl():
            tipo = "systemVerilogSource" if a.suffix in {".sv", ".svh"} else "verilogSource"
            arquivos.append({"name": f"{NO_CONTEINER_PROJETO}/{ctx.projeto.relativo(a)}",
                             "file_type": tipo})  # fmt: skip
        arquivos.append({"name": f"{NO_CONTEINER_TRABALHO}/{restricoes.name}",
                         "file_type": placa.restricoes.upper()})  # fmt: skip
        opcoes = [f"--{placa.dispositivo}", "--package", placa.pacote,
                  "--freq", f"{placa.relogio_mhz:g}", "--report", "relatorio.json"]  # fmt: skip
        # portas sem pino mapeado são posicionadas pelo nextpnr (aviso, não erro), nas duas famílias
        if placa.familia == "ice40":
            opcoes.append("--pcf-allow-unconstrained")
        elif placa.familia == "ecp5":
            opcoes.append("--lpf-allow-unconstrained")
        pedido = {
            "nome": ctx.projeto.nome.replace("-", "_"),
            "topo": ctx.projeto.projeto.topo,
            "arquivos": arquivos,
            "fluxo": placa.fluxo,
            "opcoes_nextpnr": opcoes,
            "build": f"{NO_CONTEINER_TRABALHO}/build",
            "placa": placa.id,
        }
        (ctx.dir_trabalho / "pedido.json").write_text(json.dumps(pedido, indent=2), "utf-8")
        return self.comando(ctx)

    def comando(self, ctx: Contexto) -> list[str]:
        prog = self.programa()
        usuario = (
            ["--userns=keep-id"] if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )  # fmt: skip
        caminhos = ":".join(self.perfil.imagem.caminhos)
        return [
            prog.nome, "run", "--rm", "--init", "--network=none",
            "--name", f"axil-{ctx.id_execucao}", *usuario,
            "-v", f"{ctx.projeto.raiz}:{NO_CONTEINER_PROJETO}:ro,z",
            "-v", f"{ctx.dir_trabalho}:{NO_CONTEINER_TRABALHO}:z",
            "-e", "HOME=/tmp", "-w", NO_CONTEINER_TRABALHO,
            "--entrypoint", "sh", self.perfil.imagem.referencia,
            "-c", f'export PATH="{caminhos}:$PATH"; exec python3 -u '
                  f"{NO_CONTEINER_TRABALHO}/{SCRIPT.name} {NO_CONTEINER_TRABALHO}/pedido.json",
        ]  # fmt: skip

    # --- executar e coletar -----------------------------------------------------------------

    def _build(self, ctx: Contexto) -> Path:
        return ctx.dir_trabalho / "build"

    def _relatorio(self, ctx: Contexto) -> dict | None:
        arquivo = self._build(ctx) / "relatorio.json"
        if not arquivo.is_file():
            return None
        return json.loads(arquivo.read_text(encoding="utf-8"))

    def executar(self, ctx: Contexto) -> Situacao:
        resultado = self.executor.transmitir(self.comando(ctx), ctx.ao_receber, ctx.cancelar)
        if ctx.cancelar.is_set():
            self.executor.executar(
                [self.programa().nome, "rm", "-f", f"axil-{ctx.id_execucao}"], tempo_limite=30
            )
            return Situacao.INTERROMPIDA
        return Situacao.SUCESSO if resultado.ok else Situacao.FALHA

    def descrever_progresso(self, linha: str) -> str | None:
        return next((rotulo for prefixo, rotulo in _PASSOS if linha.startswith(prefixo)), None)

    def coletar_artefatos(self, ctx: Contexto) -> list[Artefato]:
        build = self._build(ctx)
        ctx.dir_saida.mkdir(parents=True, exist_ok=True)
        artefatos = []
        candidatos = [
            *(build.glob("*.bin")), *(build.glob("*.bit")),
            build / "relatorio.json", *(ctx.dir_trabalho.glob("pinos.*")),
            build / "yosys.log", build / "next.log",
        ]  # fmt: skip
        for origem in candidatos:
            if not origem.is_file():
                continue
            if origem.suffix in {".bin", ".bit"}:
                tipo = TipoArtefato.BITSTREAM
            elif origem.name == "relatorio.json":
                tipo = TipoArtefato.RELATORIO
            else:
                tipo = TipoArtefato.OUTRO
            destino = ctx.dir_saida / origem.name
            shutil.copy2(origem, destino)
            artefatos.append(
                Artefato(
                    nome=origem.name,
                    tipo=tipo,
                    caminho=Path("saida") / origem.name,
                    bytes=destino.stat().st_size,
                )
            )
        return artefatos

    def coletar_metricas(self, ctx: Contexto) -> list[Metrica]:
        relatorio = self._relatorio(ctx)
        return relatorio_nextpnr.metricas(relatorio) if relatorio else []

    def explicar_falha(self, ctx: Contexto) -> Falha | None:
        relatorio = self._relatorio(ctx)
        if relatorio:
            falha = relatorio_nextpnr.falha_de_temporizacao(relatorio)
            if falha is not None:
                return falha
        mensagens = []
        for log in ("yosys.log", "next.log"):
            arquivo = self._build(ctx) / log
            if arquivo.is_file():
                for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
                    achado = _ERRO.match(linha.strip())
                    if achado:
                        mensagens.append(f"{log.split('.')[0]}: {achado[2]}")
        passo = "na síntese (Yosys)" if any(m.startswith("yosys") for m in mensagens) else (
            "no posicionamento e roteamento (nextpnr)"
        )  # fmt: skip
        return Falha(
            resumo=f"O fluxo de FPGA falhou {passo}."
            if mensagens
            else "O fluxo de FPGA falhou antes de produzir um relatório.",
            passo=passo,
            mensagens=mensagens[:10],
            proximo_passo="Leia as mensagens acima; o log completo está em log.txt na execução.",
        )
