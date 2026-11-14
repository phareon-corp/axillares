"""Abrir resultados nas ferramentas gráficas nativas (KLayout, Surfer).

Processos gráficos são lançados destacados: o Axillares não espera nem lê a saída deles.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from axillares.ambiente import diagnostico as dg
from axillares.ambiente.executor import Executor, ExecutorReal
from axillares.ambiente.nativas import localizar, tem_flatpak
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
