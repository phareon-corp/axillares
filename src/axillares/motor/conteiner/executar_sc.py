"""Executa uma etapa pelo SiliconCompiler. Roda DENTRO da imagem de ferramentas.

Uso: python3 executar_sc.py /trabalho/pedido.json

O pedido é escrito pelo MotorSiliconCompiler (lado de fora) e contém só dados de Axillares.
Este script é o único código nosso que importa o siliconcompiler, e ele roda na imagem fixada,
com a versão de SiliconCompiler dela. Sai com 0 em sucesso, 1 em falha do fluxo e
2 em erro de configuração; o manifesto fica em <builddir>/<design>/<job>/<design>.pkg.json.
"""

import json
import sys
from pathlib import Path

ALVOS = {
    "skywater130": "skywater130_demo",
    "gf180": "gf180_demo",
    "ihp130": "ihp130_demo",
}
FLUXOS = {"sintese": "synflow", "gds": None}  # None: o fluxo padrão do alvo (asicflow)


def principal(caminho_pedido: str) -> int:
    pedido = json.loads(Path(caminho_pedido).read_text(encoding="utf-8"))

    import siliconcompiler
    from siliconcompiler import ASIC, Design, targets

    print(f"@@axil:motor siliconcompiler {siliconcompiler.__version__}", flush=True)

    design = Design(pedido["design"])
    with design.active_fileset("rtl"):
        design.set_topmodule(pedido["topo"])
        for arquivo in pedido["rtl"]:
            design.add_file(arquivo)
    with design.active_fileset("sdc"):
        design.add_file(pedido["sdc"])

    projeto = ASIC(design)
    projeto.add_fileset(["rtl", "sdc"])
    alvo = getattr(targets, ALVOS[pedido["pdk"]])
    alvo(projeto)

    if pedido.get("chip_um"):
        largura, altura = pedido["chip_um"]
        margem = max(2.0, min(largura, altura) * 0.1)
        projeto.constraint.area.set_diearea_rectangle(
            height=altura, width=largura, coremargin=margem
        )

    projeto.option.set_builddir(pedido["builddir"])
    projeto.option.set_jobname(pedido["job"])
    projeto.option.set_nodisplay(True)
    projeto.option.set_nodashboard(True)
    if pedido.get("cachedir"):
        projeto.option.set_cachedir(pedido["cachedir"])
    fluxo = FLUXOS[pedido["etapa"]]
    if fluxo is not None:
        nome_fluxo = next((n for n in projeto.getkeys("flowgraph") if n.startswith(fluxo)), None)
        if nome_fluxo is None:
            print(f"@@axil:erro fluxo {fluxo} indisponível neste alvo", flush=True)
            return 2
        projeto.option.set_flow(nome_fluxo)

    try:
        projeto.run()
    except RuntimeError as erro:
        print(f"@@axil:falha {erro}", flush=True)
        return 1
    print("@@axil:sucesso", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1]))
