"""Abrir resultados nas ferramentas gráficas nativas (KLayout, Surfer).

Processos gráficos são lançados destacados: o Axillares não espera nem lê a saída deles.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from axillares.ambiente import diagnostico as dg
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.nativas import Lancador, flatpak_instalado, localizar, tem_flatpak
from axillares.ambiente.perfil import Origem, carregar_perfil

VISUALIZADORES = {"gds": "klayout", "onda": "surfer"}


def abrir(
    arquivo: Path, tipo: str = "gds", executor: Executor | None = None
) -> dg.Diagnostico | None:
    """Abre `arquivo` no visualizador do tipo (PATH ou Flatpak). Devolve um diagnóstico se não
    for possível."""
    nome = VISUALIZADORES[tipo]
    executor = executor or ExecutorReal()
    ferramenta = next(f for f in carregar_perfil().da_origem(Origem.NATIVA) if f.nome == nome)
    lancador = localizar(ferramenta, executor, shutil.which(nome))
    if lancador is None:
        return dg.ferramenta_nativa_ausente(
            nome,
            ferramenta.descricao,
            ferramenta.pacote,
            ferramenta.instrucao,
            flatpak=ferramenta.flatpak,
            tem_flatpak=tem_flatpak(executor),
        )
    if not arquivo.is_file():
        return dg.Diagnostico(
            codigo="arquivo-ausente",
            o_que=f"O arquivo {arquivo.name} não existe nesta execução.",
            por_que="Só execuções bem-sucedidas da etapa certa produzem esse arquivo.",
            proximo_passo="Escolha outra execução em “axil runs”.",
        )
    subprocess.Popen(
        lancador.comando(str(arquivo)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return None


# --- ondas ------------------------------------------------------------------------------------

VISUALIZADORES_ONDA = ("surfer", "gtkwave")
# O GTKWave é alternativa, sem versão conferida: ele inicia o GTK antes de ler as opções e não
# imprime a versão sem uma tela. Fedora: pacote gtkwave; Flathub: io.github.gtkwave.GTKWave
# (ambos conferidos em 2026-11-15).
GTKWAVE_FLATPAK = "io.github.gtkwave.GTKWave"


def abrir_onda(
    arquivo: Path, visualizador: str = "surfer", executor: Executor | None = None
) -> dg.Diagnostico | None:
    """Abre uma onda (.vcd/.fst) no Surfer (padrão) ou no GTKWave."""
    if visualizador not in VISUALIZADORES_ONDA:
        return dg.Diagnostico(
            codigo="visualizador-desconhecido",
            o_que=f"“{visualizador}” não é um visualizador de ondas conhecido.",
            por_que=f"Os disponíveis são: {', '.join(VISUALIZADORES_ONDA)}.",
            proximo_passo="Use --com surfer ou --com gtkwave.",
        )
    if visualizador == "surfer":
        return abrir(arquivo, "onda", executor)
    executor = executor or ExecutorReal()
    no_path = shutil.which("gtkwave")
    if no_path:
        comando = [no_path, str(arquivo)]
    elif flatpak_instalado(GTKWAVE_FLATPAK, executor):
        comando = Lancador(["flatpak", "run", "--file-forwarding", GTKWAVE_FLATPAK],
                           "flatpak").comando(str(arquivo))  # fmt: skip
    else:
        return dg.ferramenta_nativa_ausente(
            "gtkwave",
            "visualizador de formas de onda (alternativa ao Surfer)",
            "gtkwave",
            None,
            flatpak=GTKWAVE_FLATPAK,
            tem_flatpak=tem_flatpak(executor),
        )
    if not arquivo.is_file():
        return dg.Diagnostico(
            codigo="arquivo-ausente",
            o_que=f"O arquivo {arquivo.name} não existe nesta execução.",
            por_que="Só simulações e testes gravam ondas.",
            proximo_passo="Rode “axil sim” ou “axil teste” e tente de novo.",
        )
    subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)  # fmt: skip
    return None
