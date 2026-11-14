"""Ferramentas gráficas nativas: no PATH ou instaladas pelo Flatpak.

Ordem de busca: executável no PATH (pacote da distribuição, binário baixado) e, se não houver,
o aplicativo Flatpak declarado no perfil. Assim quem instalou pelo Flathub não precisa de mais
nada.
"""

from __future__ import annotations

from dataclasses import dataclass

from axillares.ambiente.executor import CODIGO_NAO_ENCONTRADO, Executor, Resultado
from axillares.ambiente.perfil import Ferramenta


@dataclass(frozen=True)
class Lancador:
    prefixo: list[str]
    """O que vem antes dos argumentos: ["/usr/bin/klayout"] ou ["flatpak", "run", "<id>"]."""
    via: str
    """"PATH" ou "flatpak"."""

    def comando(self, *arquivos: str) -> list[str]:
        if self.via == "flatpak":
            # O sandbox só enxerga algumas pastas (/tmp, por exemplo, não). Com --file-forwarding
            # os arquivos entre @@ chegam pelo portal de documentos, valha o caminho que valer.
            return [*self.prefixo, "@@", *arquivos, "@@"]
        return [*self.prefixo, *arquivos]


def flatpak_instalado(app_id: str, executor: Executor) -> bool:
    return executor.executar(["flatpak", "info", app_id], tempo_limite=15).ok


def tem_flatpak(executor: Executor) -> bool:
    return not executor.executar(["flatpak", "--version"], tempo_limite=15).nao_encontrado


def executar_versao(f: Ferramenta, executor: Executor) -> tuple[Resultado, str]:
    """Roda o comando de versão da ferramenta; devolve o resultado e por onde foi achada."""
    resultado = executor.executar(f.comando, tempo_limite=20)
    if not resultado.nao_encontrado:
        return resultado, "PATH"
    if f.flatpak and flatpak_instalado(f.flatpak, executor):
        comando = ["flatpak", "run", f.flatpak, *f.comando[1:]]
        return executor.executar(comando, tempo_limite=60), "flatpak"
    return Resultado(CODIGO_NAO_ENCONTRADO, resultado.saida), ""


def localizar(f: Ferramenta, executor: Executor, no_path: str | None) -> Lancador | None:
    """`no_path`: caminho do executável no PATH (shutil.which), se houver."""
    if no_path:
        return Lancador([no_path], "PATH")
    if f.flatpak and flatpak_instalado(f.flatpak, executor):
        return Lancador(["flatpak", "run", "--file-forwarding", f.flatpak], "flatpak")
    return None
