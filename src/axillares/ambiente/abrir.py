"""Abrir resultados nas ferramentas gráficas nativas (KLayout, Surfer).

Processos gráficos são lançados destacados: o Axillares não espera nem lê a saída deles.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from axillares.ambiente import diagnostico as dg
from axillares.ambiente.perfil import Origem, carregar_perfil

VISUALIZADORES = {"gds": "klayout", "onda": "surfer"}


def abrir(arquivo: Path, tipo: str = "gds") -> dg.Diagnostico | None:
    """Abre `arquivo` no visualizador do tipo. Devolve um diagnóstico se não for possível."""
    nome = VISUALIZADORES[tipo]
    executavel = shutil.which(nome)
    if executavel is None:
        ferramenta = next(
            (f for f in carregar_perfil().da_origem(Origem.NATIVA) if f.nome == nome), None
        )
        return dg.ferramenta_nativa_ausente(
            nome,
            ferramenta.descricao if ferramenta else nome,
            ferramenta.pacote if ferramenta else nome,
            ferramenta.instrucao if ferramenta else None,
        )
    if not arquivo.is_file():
        return dg.Diagnostico(
            codigo="arquivo-ausente",
            o_que=f"O arquivo {arquivo.name} não existe nesta execução.",
            por_que="Só execuções bem-sucedidas da etapa certa produzem esse arquivo.",
            proximo_passo="Escolha outra execução em “axil runs”.",
        )
    subprocess.Popen(
        [executavel, str(arquivo)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return None
