"""MotorSiliconCompiler: fluxo ASIC pelo SiliconCompiler, rodando dentro da imagem fixada.

O SiliconCompiler não é importado aqui: ele roda na imagem de ferramentas, na versão travada
pelo digest do perfil. Do lado de fora, este motor escreve um pedido em JSON, executa
o contêiner transmitindo o log e traduz o manifesto resultante (manifesto_sc.py).
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
from pathlib import Path

from axillares.ambiente import conteiner as ct
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import Perfil, carregar_perfil
from axillares.core.modelos import Artefato, Etapa, Falha, Metrica, Situacao, TipoArtefato
from axillares.motor import manifesto_sc
from axillares.motor.base import Contexto, ErroMotor

SCRIPT = Path(__file__).parent / "conteiner" / "executar_sc.py"
NO_CONTEINER_PROJETO = "/projeto"
NO_CONTEINER_TRABALHO = "/trabalho"
NO_CONTEINER_CACHE = "/axil-cache"
JOB = "axil"

_TIPOS = (
    (".gds.gz", TipoArtefato.GDS),
    (".gds", TipoArtefato.GDS),
    (".lvs.vg", None),
    (".lec.vg", None),
    (".vg", TipoArtefato.NETLIST),
    (".def.gz", TipoArtefato.DEF),
    (".lef", TipoArtefato.LEF),
    (".sdf", TipoArtefato.SDF),
    (".png", TipoArtefato.IMAGEM),
)


def dir_cache() -> Path:
    """Cache persistente do motor (PDKs baixados pelo próprio SiliconCompiler)."""
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "axillares" / "siliconcompiler"


def tipo_do_artefato(nome: str) -> TipoArtefato | None:
    for sufixo, tipo in _TIPOS:
        if nome.endswith(sufixo):
            return tipo
    return None


class MotorSiliconCompiler:
    nome = "siliconcompiler"

    def __init__(
        self,
        perfil: Perfil | None = None,
        executor: Executor | None = None,
        programa: ct.ProgramaConteiner | None = None,
        cache: Path | None = None,
    ) -> None:
        self.perfil = perfil or carregar_perfil()
        self.executor = executor or ExecutorReal()
        self._programa = programa
        self.cache = cache or dir_cache()

    # --- identidade -------------------------------------------------------------------------

    def versao(self) -> str:
        versao = self.perfil.motores.get(self.nome)
        if not versao:
            raise ErroMotor(
                f"O perfil {self.perfil.identificador} não declara a versão do SiliconCompiler."
            )
        return versao

    def etapas(self) -> set[Etapa]:
        return {Etapa.SINTESE, Etapa.GDS}

    def programa(self) -> ct.ProgramaConteiner:
        if self._programa is None:
            self._programa = ct.detectar_programa(self.executor)
        if self._programa is None:
            raise ErroMotor(
                "Nem podman nem docker estão instalados. Rode “axil ambiente situacao” para ver "
                "como resolver."
            )
        return self._programa

    # --- preparar ---------------------------------------------------------------------------

    def _pedido(self, ctx: Contexto) -> dict:
        p = ctx.projeto
        rtl = [f"{NO_CONTEINER_PROJETO}/{p.relativo(a)}" for a in p.arquivos_rtl()]
        sdc = p.arquivo_sdc()
        if sdc is None:
            gerado = ctx.dir_trabalho / "relogio.sdc"
            gerado.write_text(sdc_gerado(p.asic.relogio, p.asic.periodo_ns), encoding="utf-8")
            caminho_sdc = f"{NO_CONTEINER_TRABALHO}/relogio.sdc"
        else:
            caminho_sdc = f"{NO_CONTEINER_PROJETO}/{p.relativo(sdc)}"
        return {
            "design": p.nome.replace("-", "_"),
            "topo": p.projeto.topo,
            "rtl": rtl,
            "sdc": caminho_sdc,
            "pdk": p.asic.pdk.value,
            "etapa": ctx.etapa.value,
            "builddir": f"{NO_CONTEINER_TRABALHO}/build",
            "cachedir": NO_CONTEINER_CACHE,
            "job": JOB,
            "chip_um": list(p.asic.chip_um) if p.asic.chip_um else None,
        }

    def comando(self, ctx: Contexto) -> list[str]:
        prog = self.programa()
        imagem = self.perfil.imagem
        usuario = (
            ["--userns=keep-id"]
            if prog.nome == "podman"
            else ["--user", f"{os.getuid()}:{os.getgid()}"]
        )
        caminhos = ":".join(imagem.caminhos)
        return [
            prog.nome, "run", "--rm", "--init", "--name", f"axil-{ctx.id_execucao}", *usuario,
            "-v", f"{ctx.projeto.raiz}:{NO_CONTEINER_PROJETO}:ro,z",
            "-v", f"{ctx.dir_trabalho}:{NO_CONTEINER_TRABALHO}:z",
            "-v", f"{self.cache}:{NO_CONTEINER_CACHE}:z",
            "-e", "HOME=/tmp", "-w", NO_CONTEINER_TRABALHO,
            "--entrypoint", "sh", imagem.referencia,
            "-c", f'export PATH="{caminhos}:$PATH"; exec python3 -u '
                  f"{NO_CONTEINER_TRABALHO}/executar_sc.py {NO_CONTEINER_TRABALHO}/pedido.json",
        ]  # fmt: skip

    def preparar(self, ctx: Contexto) -> list[str]:
        if ctx.etapa not in self.etapas():
            raise ErroMotor(f"O SiliconCompiler não executa a etapa “{ctx.etapa}”.")
        ctx.dir_trabalho.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCRIPT, ctx.dir_trabalho / "executar_sc.py")
        pedido = self._pedido(ctx)
        (ctx.dir_trabalho / "pedido.json").write_text(
            json.dumps(pedido, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return self.comando(ctx)

    # --- executar ---------------------------------------------------------------------------

    def executar(self, ctx: Contexto) -> Situacao:
        resultado = self.executor.transmitir(self.comando(ctx), ctx.ao_receber, ctx.cancelar)
        if ctx.cancelar.is_set():
            self.executor.executar(
                [self.programa().nome, "rm", "-f", f"axil-{ctx.id_execucao}"], tempo_limite=30
            )
            return Situacao.INTERROMPIDA
        manifesto = self._manifesto(ctx)
        if manifesto is None:
            return Situacao.SUCESSO if resultado.ok else Situacao.FALHA
        return manifesto_sc.situacao(manifesto.conteudo)

    # --- coletar ----------------------------------------------------------------------------

    def _dir_job(self, ctx: Contexto) -> Path:
        return ctx.dir_trabalho / "build" / ctx.projeto.nome.replace("-", "_") / JOB

    def _manifesto(self, ctx: Contexto) -> _Manifesto | None:
        caminho = self._dir_job(ctx) / f"{ctx.projeto.nome.replace('-', '_')}.pkg.json"
        if not caminho.is_file():
            return None
        return _Manifesto(caminho, manifesto_sc.carregar(caminho))

    def coletar_artefatos(self, ctx: Contexto) -> list[Artefato]:
        manifesto = self._manifesto(ctx)
        if manifesto is None:
            return []
        finais: dict[str, Path] = {}
        for passo, indice in manifesto_sc.ordem_dos_nos(manifesto.conteudo):
            saidas = self._dir_job(ctx) / passo / indice / "outputs"
            if saidas.is_dir():
                for arquivo in sorted(saidas.iterdir()):
                    if arquivo.is_file() and tipo_do_artefato(arquivo.name):
                        finais[arquivo.name] = arquivo  # o último nó vence
        ctx.dir_saida.mkdir(parents=True, exist_ok=True)
        artefatos = []
        for nome, origem in sorted(finais.items()):
            destino = ctx.dir_saida / nome
            shutil.copy2(origem, destino)
            artefatos.append(
                Artefato(
                    nome=nome,
                    tipo=tipo_do_artefato(nome) or TipoArtefato.OUTRO,
                    caminho=Path("saida") / nome,
                    bytes=destino.stat().st_size,
                )
            )
        # o manifesto do motor fica guardado, comprimido, para retradução futura
        destino = ctx.dir_saida / "motor" / "manifesto-siliconcompiler.pkg.json.gz"
        destino.parent.mkdir(exist_ok=True)
        with manifesto.caminho.open("rb") as ent, gzip.open(destino, "wb", compresslevel=9) as sai:
            shutil.copyfileobj(ent, sai)
        artefatos.append(
            Artefato(
                nome=destino.name,
                tipo=TipoArtefato.MANIFESTO,
                caminho=Path("saida") / "motor" / destino.name,
                bytes=destino.stat().st_size,
            )
        )
        return artefatos

    def coletar_metricas(self, ctx: Contexto) -> list[Metrica]:
        manifesto = self._manifesto(ctx)
        return manifesto_sc.metricas(manifesto.conteudo) if manifesto else []

    def descrever_progresso(self, linha: str) -> str | None:
        return manifesto_sc.passo_do_log(linha)

    def explicar_falha(self, ctx: Contexto) -> Falha | None:
        manifesto = self._manifesto(ctx)
        if manifesto is None:
            return Falha(
                resumo="O SiliconCompiler não chegou a produzir um manifesto.",
                proximo_passo=(
                    "Isso costuma ser problema de ambiente, não do seu projeto. Rode “axil "
                    "ambiente verificar”; se estiver tudo certo, veja o log completo da execução."
                ),
            )
        no = manifesto_sc.no_que_falhou(manifesto.conteudo)
        log = ""
        if no is not None:
            arquivo = self._dir_job(ctx) / no[0] / no[1] / f"sc_{no[0]}_{no[1]}.log"
            if arquivo.is_file():
                log = arquivo.read_text(encoding="utf-8", errors="replace")
        return manifesto_sc.explicar_falha(
            manifesto.conteudo, log, raiz_no_conteiner=f"{NO_CONTEINER_PROJETO}/"
        )


class _Manifesto:
    __slots__ = ("caminho", "conteudo")

    def __init__(self, caminho: Path, conteudo: dict) -> None:
        self.caminho = caminho
        self.conteudo = conteudo


def sdc_gerado(relogio: str, periodo_ns: float) -> str:
    """SDC mínimo quando o projeto não traz o seu: um relógio na frequência alvo."""
    atraso = round(periodo_ns * 0.2, 3)
    return (
        "# Gerado pelo Axillares a partir de asic.frequencia_mhz (axil.toml).\n"
        f"create_clock -name {relogio} -period {periodo_ns:.3f} [get_ports {{{relogio}}}]\n"
        f"set_input_delay {atraso} -clock {relogio} [all_inputs]\n"
        f"set_output_delay {atraso} -clock {relogio} [all_outputs]\n"
    )
