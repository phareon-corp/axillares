"""Comandos de projeto: novo, executar, runs e comparar."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from axillares.ambiente.abrir import abrir as abrir_visualizador
from axillares.core import formato as fmt
from axillares.core import recentes
from axillares.core.caderno import Caderno, ErroCaderno, RegistroExecucao
from axillares.core.comparacao import comparar
from axillares.core.execucao import executar_etapa
from axillares.core.modelos import Etapa, Situacao, TipoArtefato
from axillares.core.novo import criar_projeto
from axillares.core.projeto import ErroProjeto, Projeto, carregar_projeto
from axillares.motor import ErroMotor, Motor, obter_motor

console = Console()
ACENTO = "#FF4A1C"
COR_SITUACAO = {
    Situacao.SUCESSO: "green",
    Situacao.FALHA: "red",
    Situacao.INTERROMPIDA: "yellow",
    Situacao.EM_ANDAMENTO: "dim",
}
COR_TENDENCIA = {"melhor": "green", "pior": "red", "igual": "dim", "neutra": ""}

OpcaoProjeto = typer.Option(None, "--projeto", "-C", help="Pasta do projeto (padrão: atual).")

# Ponto de injeção para testes: devolve o motor pelo nome.
fabrica_motor = obter_motor


def _erro(mensagem: str, codigo: int = 2) -> typer.Exit:
    console.print(f"[bold red]✕[/] {mensagem}")
    return typer.Exit(codigo)


def _projeto(pasta: Path | None) -> Projeto:
    try:
        projeto = carregar_projeto(pasta)
    except ErroProjeto as erro:
        raise _erro(str(erro)) from erro
    recentes.registrar(projeto.raiz, projeto.nome)
    return projeto


# --- novo ---------------------------------------------------------------------------------


def novo(
    nome: str = typer.Argument(..., help="Nome do projeto (vira o nome da pasta)."),
    modelo: str = typer.Option("vazio", "--modelo", "-m", help="Veja as opções com: axil modelos"),
    pdk: str = typer.Option("skywater130", "--pdk", help="skywater130, gf180 ou ihp130."),
    frequencia: float = typer.Option(100.0, "--frequencia", "-f", help="Relógio alvo, em MHz."),
    em: Path = typer.Option(Path("."), "--em", help="Pasta onde criar o projeto."),
) -> None:
    """Cria um projeto a partir de um modelo (em branco, portas, contador, semáforo)."""
    try:
        pasta = criar_projeto(nome, em, modelo, pdk, frequencia)
    except ErroProjeto as erro:
        raise _erro(str(erro)) from erro
    recentes.registrar(pasta, nome)
    console.print(
        f"[green]✓[/] Projeto [bold]{nome}[/] criado em {pasta} [dim](modelo {modelo})[/]"
    )
    console.print(f"  [dim]próximo passo:[/] cd {pasta} && axil executar sintese")


def modelos_cmd() -> None:
    """Lista os modelos de projeto disponíveis para `axil novo --modelo`."""
    from axillares.core.novo import modelos

    t = Table(header_style="dim", border_style="grey30", box=None, padding=(0, 2))
    t.add_column("MODELO", style="bold", no_wrap=True)
    t.add_column("NÍVEL", style="dim", no_wrap=True)
    t.add_column("O QUE É")
    for m in modelos():
        t.add_row(m.id, m.nivel, f"[bold]{m.titulo}[/] — {m.descricao}")
    console.print(t)


# --- executar -----------------------------------------------------------------------------


def _resumo_metricas(r: RegistroExecucao) -> Text:
    texto = Text()
    for chave, (rotulo, casas) in fmt.METRICAS_PRINCIPAIS.items():
        m = r.metrica(chave)
        if m is None:
            continue
        texto.append(f"{rotulo.upper()} ", style="dim")
        texto.append(fmt.numero(m.valor, casas))
        if m.unidade:
            texto.append(f" {m.unidade}", style="dim")
        texto.append("   ")
    return texto


def mostrar_desfecho(r: RegistroExecucao, raiz: Path) -> None:
    cor = COR_SITUACAO[r.situacao]
    simbolo = {"sucesso": "✓", "falha": "✕", "interrompida": "■"}.get(r.situacao.value, "·")
    console.print(
        f"[{cor}]{simbolo} {fmt.ROTULO_SITUACAO[r.situacao]}[/] em {fmt.duracao(r.duracao_s)}"
        f"  [dim]· execução[/] [bold]#{r.numero}[/]  [dim]{r.id}[/]"
    )
    if r.situacao is Situacao.SUCESSO:
        console.print("  ", _resumo_metricas(r))
        for a in r.artefatos:
            if a.tipo in {TipoArtefato.GDS, TipoArtefato.NETLIST}:
                caminho = (r.diretorio / a.caminho).relative_to(raiz) if r.diretorio else a.caminho
                console.print(f"  [dim]{a.tipo.value.upper():8}[/] {caminho}")
    elif r.falha:
        corpo: list = [Text(r.falha.resumo, style="bold")]
        if r.falha.mensagens:
            corpo.append(Text("\n".join(r.falha.mensagens), style="dim"))
        if r.falha.proximo_passo:
            corpo.append(Text.assemble(("→ ", ACENTO), (r.falha.proximo_passo, "")))
        log = (r.diretorio / "log.txt").relative_to(raiz) if r.diretorio else "log.txt"
        corpo.append(Text(f"log completo: {log}", style="dim italic"))
        console.print(Panel(Group(*corpo), border_style=cor, padding=(0, 1)))


def executar(
    etapa: Etapa = typer.Argument(..., help="sintese ou gds"),
    pasta: Path | None = OpcaoProjeto,
    log: bool = typer.Option(False, "--log", help="Transmite o log completo do motor."),
) -> None:
    """Executa uma etapa do fluxo e grava a execução no caderno (runs/)."""
    projeto = _projeto(pasta)
    nome_motor = projeto.motores.para(etapa)
    try:
        motor: Motor = fabrica_motor(nome_motor)
        versao = motor.versao()
    except ErroMotor as erro:
        raise _erro(str(erro)) from erro

    console.print(
        f"[{ACENTO}]●[/] [bold]{etapa.value.upper()}[/] [dim]{etapa.descricao}[/]  ·  "
        f"{projeto.nome}  ·  {nome_motor} {versao}"
    )
    cancelar = threading.Event()
    estado = {"passo": "preparando", "inicio": time.monotonic(), "resultado": None, "erro": None}

    def receber(linha: str) -> None:
        if log:
            console.print(Text(linha, style="dim"), highlight=False)
        passo = motor.descrever_progresso(linha)
        if passo:
            estado["passo"] = passo

    terminou = threading.Event()

    def rodar() -> None:
        try:
            estado["resultado"] = executar_etapa(
                projeto, etapa, motor, ao_receber=receber, cancelar=cancelar
            )
        except Exception as erro:  # pragma: no cover - executar_etapa já captura tudo
            estado["erro"] = erro
        finally:
            terminou.set()

    linha_viva = Spinner("dots", style=ACENTO)
    # Não-daemon e esperado por um Event: um Thread.join() atingido por Ctrl+C pode passar a
    # retornar antes da hora, e o registro da execução ficaria sem ser fechado.
    trabalhador = threading.Thread(target=rodar, name="axil-execucao")
    trabalhador.start()
    try:
        with Live(console=console, refresh_per_second=8, transient=True) as ao_vivo:
            while not terminou.is_set():
                decorrido = time.monotonic() - estado["inicio"]
                linha_viva.text = Text.assemble(
                    (f" {estado['passo']}", ""), (f"   {fmt.duracao(decorrido)}", "dim")
                )
                if not log:
                    ao_vivo.update(linha_viva)
                terminou.wait(0.12)
    except KeyboardInterrupt:
        console.print("[yellow]■[/] Interrompendo… (o registro da execução será guardado)")
        cancelar.set()
        while not terminou.wait(0.5):
            pass

    if estado["erro"] is not None:  # pragma: no cover
        raise estado["erro"]
    registro: RegistroExecucao = estado["resultado"]
    mostrar_desfecho(registro, projeto.raiz)
    if registro.situacao is not Situacao.SUCESSO:
        raise typer.Exit(1)


# --- runs ---------------------------------------------------------------------------------


def runs(
    etapa: Etapa | None = typer.Option(None, "--etapa", "-e", help="Filtra por etapa."),
    recuperar: bool = typer.Option(
        False, "--recuperar", help="Fecha como interrompidas as execuções abandonadas."
    ),
    pasta: Path | None = OpcaoProjeto,
) -> None:
    """Lista as execuções do projeto, da mais nova para a mais antiga."""
    projeto = _projeto(pasta)
    caderno = Caderno(projeto.dir_runs)
    if recuperar:
        for r in caderno.recuperar(projeto):
            console.print(f"[yellow]■[/] #{r.numero} {r.id} fechada como interrompida.")
    abandonadas = caderno.abandonadas()
    registros = caderno.listar(etapa)
    if not registros:
        console.print("[dim]Nenhuma execução ainda.[/] Rode “axil executar sintese”.")
        return
    principais = {
        chave: info
        for chave, info in fmt.METRICAS_PRINCIPAIS.items()
        if any(r.metrica(chave) for r in registros)
    }
    t = Table(header_style="dim", border_style="grey30", pad_edge=False, box=None, padding=(0, 1))
    t.add_column("#", justify="right", style="bold", no_wrap=True)
    t.add_column("ETAPA", no_wrap=True)
    t.add_column("", no_wrap=True)
    t.add_column("INÍCIO", no_wrap=True)
    t.add_column("DURAÇÃO", justify="right", no_wrap=True)
    unidades = []
    for chave, (rotulo, _c) in principais.items():
        t.add_column(rotulo.upper(), justify="right", no_wrap=True)
        unidade = next((r.metrica(chave).unidade for r in registros if r.metrica(chave)), "")
        if unidade:
            unidades.append(f"{rotulo} em {unidade}")
    t.add_column("RTL", style="dim", no_wrap=True)
    hashes = [r.hash_rtl for r in registros]
    simbolos = {Situacao.SUCESSO: "✓", Situacao.FALHA: "✕", Situacao.INTERROMPIDA: "■"}
    for r in registros:
        cor = COR_SITUACAO[r.situacao]
        celulas = []
        for chave, (_r, casas) in principais.items():
            m = r.metrica(chave)
            celulas.append(fmt.numero(m.valor, casas) if m else "[dim]—[/]")
        repetido = "≡" if hashes.count(r.hash_rtl) > 1 else " "
        t.add_row(
            str(r.numero), r.etapa.value, f"[{cor}]{simbolos.get(r.situacao, '·')}[/]",
            fmt.momento(r.inicio), fmt.duracao(r.duracao_s), *celulas,
            f"{repetido} {r.hash_curto}",
        )  # fmt: skip
    console.print(t)
    console.print(f"[dim]{' · '.join(unidades)}[/]" if unidades else "")
    console.print("[dim]✓ sucesso  ✕ falha  ■ interrompida  ≡ mesmo RTL[/]")
    console.print("[dim]compare duas: axil comparar penultima ultima[/]")
    if abandonadas:
        console.print(
            f"[yellow]![/] {len(abandonadas)} execução(ões) ficaram pela metade (o Axillares foi "
            "encerrado durante elas). Para registrá-las: [bold]axil runs --recuperar[/]"
        )


# --- comparar -----------------------------------------------------------------------------


def comparar_cmd(
    a: str = typer.Argument(..., help="Execução A: número, prefixo do id, ultima ou penultima."),
    b: str = typer.Argument(..., help="Execução B (a comparada contra A)."),
    pasta: Path | None = OpcaoProjeto,
) -> None:
    """Compara as métricas de duas execuções: valor de cada uma, diferença e percentual."""
    projeto = _projeto(pasta)
    caderno = Caderno(projeto.dir_runs)
    try:
        ra, rb = caderno.resolver(a), caderno.resolver(b)
    except ErroCaderno as erro:
        raise _erro(str(erro)) from erro
    c = comparar(ra, rb)
    for rotulo, r in (("A", ra), ("B", rb)):
        console.print(
            f"[{ACENTO}]{rotulo}[/] [bold]#{r.numero}[/] {r.etapa.value} · "
            f"{fmt.ROTULO_SITUACAO[r.situacao]} · {fmt.momento(r.inicio)}  [dim]{r.id}[/]"
        )
    if c.mesmo_rtl:
        console.print(
            f"[green]≡[/] mesmo RTL [dim](hash {ra.hash_curto})[/]: "
            "a diferença vem de restrições, configuração ou motor."
        )
    else:
        console.print(f"[yellow]≠[/] RTL diferente [dim]({ra.hash_curto} → {rb.hash_curto})[/]")
    if not c.mesma_etapa:
        console.print("[yellow]![/] Etapas diferentes: nem toda métrica é comparável.")
    if not c.mesma_versao_motor:
        console.print(
            f"[yellow]![/] Versões de motor diferentes: {ra.motor} {ra.versao_motor} "
            f"→ {rb.motor} {rb.versao_motor}."
        )
    t = Table(header_style="dim", border_style="grey30", pad_edge=False)
    for coluna, alinhamento in (
        ("MÉTRICA", "left"),
        ("A", "right"),
        ("B", "right"),
        ("Δ", "right"),
        ("Δ %", "right"),
    ):
        t.add_column(coluna, justify=alinhamento)  # type: ignore[arg-type]
    for linha in c.linhas:
        casas = fmt.casas_para(linha.chave, linha.a, linha.b)
        cor = COR_TENDENCIA[linha.tendencia]
        delta = fmt.numero(linha.delta, casas, sinal=True)
        pct = (
            fmt.numero(linha.delta_pct, 1, sinal=True) + " %"
            if linha.delta_pct is not None
            else "—"
        )
        unidade = f" [dim]{linha.unidade}[/]" if linha.unidade else ""
        t.add_row(
            f"{linha.rotulo}{unidade}", fmt.numero(linha.a, casas), fmt.numero(linha.b, casas),
            f"[{cor}]{delta}[/]" if cor else delta, f"[{cor}]{pct}[/]" if cor else pct,
        )  # fmt: skip
    console.print(t)
    console.print("[dim]verde: melhorou de A para B · vermelho: piorou[/]")


# --- abrir --------------------------------------------------------------------------------


def abrir(
    referencia: str = typer.Argument("ultima", help="Execução: número, prefixo, ultima…"),
    pasta: Path | None = OpcaoProjeto,
) -> None:
    """Abre o GDS de uma execução no KLayout."""
    projeto = _projeto(pasta)
    try:
        r = Caderno(projeto.dir_runs).resolver(referencia)
    except ErroCaderno as erro:
        raise _erro(str(erro)) from erro
    gds = next((a for a in r.artefatos if a.tipo is TipoArtefato.GDS), None)
    if gds is None or r.diretorio is None:
        raise _erro(
            f"A execução #{r.numero} ({r.etapa.value}, {fmt.ROTULO_SITUACAO[r.situacao]}) não tem "
            "GDS. Só a etapa gds bem-sucedida produz um."
        )
    from axillares.cli.ambiente import painel_diagnostico

    diag = abrir_visualizador(r.diretorio / gds.caminho, "gds")
    if diag is not None:
        console.print(painel_diagnostico(diag))
        raise typer.Exit(1)
    console.print(f"[green]✓[/] Abrindo {gds.nome} da execução #{r.numero} no KLayout.")


# --- layout -------------------------------------------------------------------------------


def layout(
    referencia: str = typer.Argument("ultima", help="Execução: número, prefixo, ultima…"),
    saida: Path = typer.Option(Path("layout.png"), "--saida", "-o", help="Imagem PNG a gravar."),
    largura: int = typer.Option(1600, "--largura", help="Largura em pixels."),
    altura: int = typer.Option(1200, "--altura", help="Altura em pixels."),
    pasta: Path | None = OpcaoProjeto,
) -> None:
    """Desenha o layout (GDS) de uma execução numa imagem, pelo KLayout da imagem de ferramentas."""
    from axillares.motor.base import ErroMotor
    from axillares.motor.layout import RenderizadorLayout

    projeto = _projeto(pasta)
    try:
        r = Caderno(projeto.dir_runs).resolver(referencia)
    except ErroCaderno as erro:
        raise _erro(str(erro)) from erro
    gds = next((a for a in r.artefatos if a.tipo is TipoArtefato.GDS), None)
    if gds is None or r.diretorio is None:
        raise _erro(f"A execução #{r.numero} não tem GDS. Só a etapa gds bem-sucedida produz um.")
    pdk = r.pdk or projeto.asic.pdk.value
    try:
        with RenderizadorLayout(r.diretorio / gds.caminho, pdk) as render:
            info = render.iniciar()
            imagem = render.renderizar(largura, altura, fundo="#08080B")
            saida.write_bytes(imagem.arquivo.read_bytes())
    except ErroMotor as erro:
        raise _erro(str(erro), 1) from erro
    x1, y1, x2, y2 = info.caixa
    console.print(
        f"[green]✓[/] {saida}  [dim]célula {info.celula} · "
        f"{fmt.numero(x2 - x1, 2)} × {fmt.numero(y2 - y1, 2)} µm · {len(info.camadas)} camadas · "
        f"PDK {pdk}[/]"
    )
