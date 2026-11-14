"""Avaliação do ambiente: a função que alimenta `axil ambiente situacao|verificar` e a GUI."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from axillares.ambiente import conteiner as ct
from axillares.ambiente import diagnostico as dg
from axillares.ambiente.executor import Executor, Resultado
from axillares.ambiente.nativas import executar_versao, tem_flatpak
from axillares.ambiente.perfil import Comparacao, Ferramenta, Origem, Perfil, comparar_versoes


class Veredito(StrEnum):
    OK = "ok"
    DIVERGENTE = "divergente"
    AUSENTE = "ausente"
    SEM_IMAGEM = "sem imagem"
    ILEGIVEL = "ilegível"


@dataclass(frozen=True)
class FerramentaAvaliada:
    ferramenta: Ferramenta
    veredito: Veredito
    encontrada: str | None = None
    diagnostico: dg.Diagnostico | None = None
    via: str = ""
    """Para nativas: "PATH" ou "flatpak"."""

    @property
    def nome(self) -> str:
        return self.ferramenta.nome

    @property
    def aprovada(self) -> bool:
        return self.veredito is Veredito.OK or not self.ferramenta.essencial


@dataclass
class RelatorioAmbiente:
    perfil: Perfil
    programa: ct.ProgramaConteiner | None
    imagem: ct.PresencaImagem | None
    ferramentas: list[FerramentaAvaliada] = field(default_factory=list)
    diagnosticos: list[dg.Diagnostico] = field(default_factory=list)
    """Problemas do ambiente em si (contêiner, imagem), antes das ferramentas."""

    @property
    def aprovado(self) -> bool:
        return not any(d.bloqueante for d in self.diagnosticos) and all(
            f.aprovada for f in self.ferramentas
        )

    @property
    def todos_os_diagnosticos(self) -> list[dg.Diagnostico]:
        vistos: set[tuple[str, str]] = set()
        lista = []
        for d in [*self.diagnosticos, *(f.diagnostico for f in self.ferramentas if f.diagnostico)]:
            chave = (d.codigo, d.o_que)
            if chave not in vistos:
                vistos.add(chave)
                lista.append(d)
        return sorted(lista, key=lambda d: not d.bloqueante)

    def contagem(self) -> dict[Veredito, int]:
        return {v: sum(1 for f in self.ferramentas if f.veredito is v) for v in Veredito}


def avaliar_ferramenta(
    ferramenta: Ferramenta,
    resultado: Resultado,
    os_release: Path = Path("/etc/os-release"),
    flatpak_existe: bool = True,
) -> FerramentaAvaliada:
    if resultado.nao_encontrado:
        if ferramenta.origem is Origem.NATIVA:
            diag = dg.ferramenta_nativa_ausente(
                ferramenta.nome,
                ferramenta.descricao,
                ferramenta.pacote,
                ferramenta.instrucao,
                os_release,
                ferramenta.flatpak,
                flatpak_existe,
            )
        else:
            diag = dg.ferramenta_ausente_na_imagem(ferramenta.nome, resultado.saida)
        return FerramentaAvaliada(ferramenta, Veredito.AUSENTE, None, diag)

    encontrada = ferramenta.extrair_versao(resultado.saida)
    if encontrada is None:
        diag = dg.versao_ilegivel(ferramenta.nome, resultado.saida)
        return FerramentaAvaliada(ferramenta, Veredito.ILEGIVEL, None, diag)

    if comparar_versoes(encontrada, ferramenta.versao, ferramenta.comparacao):
        return FerramentaAvaliada(ferramenta, Veredito.OK, encontrada)
    diag = dg.versao_divergente(
        ferramenta.nome, encontrada, ferramenta.versao,
        ferramenta.comparacao is Comparacao.MINIMA, ferramenta.essencial,
    )  # fmt: skip
    return FerramentaAvaliada(ferramenta, Veredito.DIVERGENTE, encontrada, diag)


def avaliar_ambiente(
    perfil: Perfil, executor: Executor, os_release: Path = Path("/etc/os-release")
) -> RelatorioAmbiente:
    programa = ct.detectar_programa(executor)
    relatorio = RelatorioAmbiente(perfil, programa, None)
    do_conteiner = perfil.da_origem(Origem.CONTEINER)

    if programa is None:
        relatorio.diagnosticos.append(dg.sem_conteiner(os_release))
        relatorio.ferramentas += [FerramentaAvaliada(f, Veredito.SEM_IMAGEM) for f in do_conteiner]
    else:
        consulta = ct.consultar_imagem(programa, perfil.imagem, executor)
        relatorio.imagem = consulta.presenca
        if consulta.diagnostico:
            relatorio.diagnosticos.append(consulta.diagnostico)
        if consulta.presenca is ct.PresencaImagem.PRESENTE:
            if not ct.digest_confere(perfil.imagem, consulta.digests):
                relatorio.diagnosticos.append(
                    dg.digest_divergente(perfil.imagem.digest, consulta.digests)
                )
            relatorio.ferramentas += _avaliar_no_conteiner(
                programa, perfil, do_conteiner, executor, relatorio, os_release
            )
        else:
            relatorio.ferramentas += [
                FerramentaAvaliada(f, Veredito.SEM_IMAGEM) for f in do_conteiner
            ]

    nativas = perfil.da_origem(Origem.NATIVA)
    flatpak_existe = nativas and tem_flatpak(executor)
    for f in nativas:
        resultado, via = executar_versao(f, executor)
        avaliada = avaliar_ferramenta(f, resultado, os_release, bool(flatpak_existe))
        relatorio.ferramentas.append(replace(avaliada, via=via))
    return relatorio


def _avaliar_no_conteiner(
    programa: ct.ProgramaConteiner,
    perfil: Perfil,
    ferramentas: list[Ferramenta],
    executor: Executor,
    relatorio: RelatorioAmbiente,
    os_release: Path,
) -> list[FerramentaAvaliada]:
    por_nome, bruto = ct.sondar(programa, perfil.imagem, ferramentas, executor)
    if not por_nome and not bruto.ok:
        relatorio.diagnosticos.append(
            dg.conteiner_falhou(programa.nome, "executar a imagem", bruto.saida)
        )
        return [FerramentaAvaliada(f, Veredito.SEM_IMAGEM) for f in ferramentas]
    avaliadas = []
    for f in ferramentas:
        resultado = por_nome.get(f.nome, Resultado(127, "sem resposta da sonda"))
        avaliadas.append(avaliar_ferramenta(f, resultado, os_release))
    return avaliadas
