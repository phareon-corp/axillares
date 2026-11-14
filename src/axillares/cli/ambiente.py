"""`axil ambiente` — situação, instalação e verificação do toolchain."""

from __future__ import annotations

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from axillares.ambiente import conteiner as ct
from axillares.ambiente.diagnostico import Diagnostico
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.perfil import PERFIL_PADRAO, ErroPerfil, Perfil, carregar_perfil
from axillares.ambiente.verificacao import RelatorioAmbiente, Veredito, avaliar_ambiente

app = typer.Typer(help="Provisiona e verifica o toolchain de EDA.", no_args_is_help=True)
console = Console()

ACENTO = "#FF4A1C"
_ESTILO_VEREDITO = {
    Veredito.OK: ("green", "● ok"),
    Veredito.DIVERGENTE: ("red", "● divergente"),
    Veredito.AUSENTE: ("red", "○ ausente"),
    Veredito.SEM_IMAGEM: ("yellow", "○ sem imagem"),
    Veredito.ILEGIVEL: ("yellow", "◐ ilegível"),
}

_ROTULO_ORIGEM = {"conteiner": "contêiner", "nativa": "nativa"}

OpcaoPerfil = typer.Option(PERFIL_PADRAO, "--perfil", "-p", help="Nome ou caminho do perfil.")

# Ponto de injeção para os testes da CLI.
fabrica_executor: type[Executor] | None = None


def _executor() -> Executor:
    return fabrica_executor() if fabrica_executor else ExecutorReal()


def _perfil(nome: str) -> Perfil:
    try:
        return carregar_perfil(nome)
    except ErroPerfil as erro:
        console.print(f"[bold red]✕[/] {erro}")
        raise typer.Exit(2) from erro


def painel_diagnostico(d: Diagnostico) -> Panel:
    cor = "red" if d.bloqueante else "yellow"
    corpo = [
        Text(d.o_que, style="bold"),
        Text(d.por_que, style="dim"),
        Text.assemble(("→ ", ACENTO), (d.proximo_passo, "")),
    ]
    if d.detalhe:
        corpo.append(Text(d.detalhe, style="dim italic"))
    rotulo = "BLOQUEANTE" if d.bloqueante else "AVISO"
    return Panel(
        Group(*corpo),
        title=f"[{cor}]{rotulo}[/] · {d.codigo}",
        title_align="left",
        border_style=cor,
        padding=(0, 1),
    )


def tabela(relatorio: RelatorioAmbiente) -> Table:
    t = Table(header_style="dim", border_style="grey30", expand=False, pad_edge=False)
    t.add_column("FERRAMENTA", no_wrap=True)
    t.add_column("ORIGEM", no_wrap=True)
    t.add_column("ENCONTRADA", overflow="fold")
    t.add_column("ESPERADA", overflow="fold")
    t.add_column("VEREDITO", no_wrap=True)
    for f in relatorio.ferramentas:
        cor, rotulo = _ESTILO_VEREDITO[f.veredito]
        esperada = f.ferramenta.versao + (" ou +" if f.ferramenta.comparacao == "minima" else "")
        nome = f.nome if f.ferramenta.essencial else f"{f.nome} [dim](opcional)[/]"
        t.add_row(
            nome,
            _ROTULO_ORIGEM[f.ferramenta.origem],
            f.encontrada or "—",
            esperada,
            f"[{cor}]{rotulo}[/]",
        )
    return t


def _cabecalho(relatorio: RelatorioAmbiente) -> None:
    p = relatorio.perfil
    console.print(f"[{ACENTO}]●[/] [bold]PERFIL[/] {p.identificador}  [dim]{p.descricao}[/]")
    programa = str(relatorio.programa) if relatorio.programa else "[red]nenhum[/]"
    imagem = relatorio.imagem.value if relatorio.imagem else "—"
    console.print(
        f"  [dim]CONTÊINER[/] {programa}   [dim]IMAGEM[/] {imagem}   "
        f"[dim]{p.imagem.repositorio}:{p.imagem.tag}[/]"
    )
    console.print()


def _rodape(relatorio: RelatorioAmbiente) -> None:
    for d in relatorio.todos_os_diagnosticos:
        console.print(painel_diagnostico(d))
    if relatorio.aprovado:
        console.print(
            f"[green]✓[/] Ambiente pronto para o perfil {relatorio.perfil.identificador}."
        )
    else:
        console.print("[red]✕[/] Ambiente incompleto — siga o próximo passo indicado acima.")


@app.command("situacao")
def situacao(perfil: str = OpcaoPerfil) -> None:
    """Mostra cada ferramenta do perfil com origem, versão encontrada, esperada e veredito."""
    p = _perfil(perfil)
    with console.status("Consultando o ambiente…"):
        relatorio = avaliar_ambiente(p, _executor())
    _cabecalho(relatorio)
    console.print(tabela(relatorio))
    console.print()
    _rodape(relatorio)


@app.command("verificar")
def verificar(perfil: str = OpcaoPerfil) -> None:
    """Executa cada ferramenta e confere a versão. Sai com código 1 se algo essencial falhar."""
    p = _perfil(perfil)
    with console.status("Executando cada ferramenta…"):
        relatorio = avaliar_ambiente(p, _executor())
    contagem = relatorio.contagem()
    console.print(f"{contagem[Veredito.OK]}/{len(relatorio.ferramentas)} ferramentas conferidas.")
    _rodape(relatorio)
    if not relatorio.aprovado:
        raise typer.Exit(1)


@app.command("instalar")
def instalar(perfil: str = OpcaoPerfil) -> None:
    """Baixa a imagem de ferramentas fixada por digest (podman ou docker) e confere o digest."""
    p = _perfil(perfil)
    executor = _executor()
    relatorio = RelatorioAmbiente(p, ct.detectar_programa(executor), None)
    if relatorio.programa is None:
        from axillares.ambiente.diagnostico import sem_conteiner

        console.print(painel_diagnostico(sem_conteiner()))
        raise typer.Exit(1)
    programa = relatorio.programa

    consulta = ct.consultar_imagem(programa, p.imagem, executor)
    if consulta.presenca is ct.PresencaImagem.PRESENTE and ct.digest_confere(
        p.imagem, consulta.digests
    ):
        console.print("[green]✓[/] A imagem já está baixada e confere com o digest do perfil.")
        console.print(f"  [dim]{p.imagem.referencia}[/]")
        return
    if consulta.presenca is ct.PresencaImagem.ERRO and consulta.diagnostico:
        console.print(painel_diagnostico(consulta.diagnostico))
        raise typer.Exit(1)

    console.print(
        f"[{ACENTO}]●[/] Baixando [bold]{p.imagem.repositorio}:{p.imagem.tag}[/] "
        f"com {programa} — cerca de {p.imagem.tamanho_gb:.0f} GB, uma vez só."
    )
    console.print(f"  [dim]digest {p.imagem.digest}[/]")
    with Progress(
        TextColumn("[dim]CAMADAS[/]"),
        BarColumn(complete_style=ACENTO, finished_style="green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as barra:
        tarefa = barra.add_task("download", total=p.imagem.camadas)
        resultado = ct.baixar_imagem(
            programa,
            p.imagem,
            executor,
            lambda prog: barra.update(tarefa, completed=prog.camadas),
        )
    if not resultado.ok:
        if resultado.diagnostico:
            console.print(painel_diagnostico(resultado.diagnostico))
        raise typer.Exit(1)
    console.print(
        "[green]✓[/] Imagem baixada e digest verificado. "
        "Rode “axil ambiente verificar” para conferir cada ferramenta."
    )
