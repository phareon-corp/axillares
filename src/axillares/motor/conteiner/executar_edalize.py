"""Executa o fluxo de FPGA pelo Edalize. Roda DENTRO da imagem de ferramentas.

Uso: python3 executar_edalize.py /trabalho/pedido.json

O Edalize gera o Makefile que encadeia Yosys → nextpnr → empacotador de bitstream; o Axillares
não encadeia ferramentas. Sai com 0 em sucesso e 1 em falha; o relatório do nextpnr
(--report) fica em <build>/relatorio.json mesmo quando a temporização falha.
"""

import json
import os
import sys
from pathlib import Path

FLUXOS = {"icestorm": ("edalize.flows.icestorm", "Icestorm"),
          "trellis": ("edalize.flows.trellis", "Trellis")}  # fmt: skip


def principal(caminho_pedido: str) -> int:
    pedido = json.loads(Path(caminho_pedido).read_text(encoding="utf-8"))
    import importlib

    import edalize

    versao = getattr(edalize, "__version__", None)
    if versao is None:
        from importlib.metadata import version

        versao = version("edalize")
    print(f"@@axil:motor edalize {versao}", flush=True)

    modulo, classe = FLUXOS[pedido["fluxo"]]
    Fluxo = getattr(importlib.import_module(modulo), classe)
    edam = {
        "name": pedido["nome"],
        "toplevel": pedido["topo"],
        "files": pedido["arquivos"],
        "flow_options": {"nextpnr_options": pedido["opcoes_nextpnr"]},
    }
    build = pedido["build"]
    os.makedirs(build, exist_ok=True)
    fluxo = Fluxo(edam, build, verbose=False)
    fluxo.configure()
    try:
        fluxo.build()
    except RuntimeError as erro:
        print(f"@@axil:falha {erro}", flush=True)
        return 1
    print("@@axil:sucesso", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1]))
