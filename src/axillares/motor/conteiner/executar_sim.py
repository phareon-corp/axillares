"""Executa simulação (testbench clássico) ou testes cocotb pelo Edalize. Roda DENTRO da imagem.

Uso: python3 executar_sim.py /trabalho/pedido.json

Quem compila e roda é o fluxo `sim` do Edalize (Icarus ou Verilator; cocotb pela opção
`cocotb_module`). Este script só completa o que o Edalize 0.6.8 não faz sozinho:
  - GPI_USERS, exigido pelo cocotb 2.1 (o mesmo valor que o runner do próprio cocotb monta);
  - um módulo com $dumpfile para haver onda nos testes cocotb (como o runner do cocotb faz);
  - -g2012 para o Icarus aceitar SystemVerilog (enum, always_ff, task com vários comandos…);
  - um limite de tempo, para um testbench sem $finish não rodar para sempre;
  - a extensão certa da onda: o Edalize chama o vvp sempre com -fst, então um $dumpfile("x.vcd")
    grava FST com nome de VCD. Todo VCD começa com "$"; se não começar, vira .fst.
Linhas "@@axil:…" marcam passos e o desfecho para o lado de fora.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

MODULO_ONDA = """module axil_onda();
initial begin
    $dumpfile("onda.fst");
    $dumpvars(0, {topo});
end
endmodule
"""


class _Limite(Exception):
    pass


def _ao_estourar(_sinal, _quadro):
    raise _Limite


def _cocotb_config(*args):
    saida = subprocess.run(["cocotb-config", *args], capture_output=True, text=True, check=True)
    return saida.stdout.strip()


def _corrigir_extensoes(build: Path) -> None:
    for onda in build.glob("*.vcd"):
        with onda.open("rb") as arquivo:
            inicio = arquivo.read(64).lstrip()
        if inicio and not inicio.startswith(b"$"):
            onda.rename(onda.with_suffix(".fst"))


def principal(caminho_pedido: str) -> int:
    pedido = json.loads(Path(caminho_pedido).read_text(encoding="utf-8"))
    from importlib.metadata import version

    from edalize.flows.sim import Sim

    print(f"@@axil:motor edalize {version('edalize')}", flush=True)
    build = Path(pedido["build"])
    build.mkdir(parents=True, exist_ok=True)
    simulador = pedido["simulador"]
    opcoes = {"tool": simulador}
    arquivos = list(pedido["arquivos"])
    topo = pedido["topo"]
    if simulador == "icarus":
        # -g2012: o Icarus só aceita SystemVerilog com ela, e o Edalize não a passa nem para .sv
        opcoes.update(timescale=pedido["timescale"], iverilog_options=["-g2012"])
    elif simulador == "verilator":
        # VCD: o rastreamento FST do Verilator não compila na imagem (falta lz4.h)
        opcoes.update(mode="binary", verilator_options=["--timing", "--trace", "-Wno-fatal"])

    if pedido["modo"] == "cocotb":
        onda = build / "axil_onda.v"
        onda.write_text(MODULO_ONDA.format(topo=topo), encoding="utf-8")
        arquivos.append({"name": str(onda), "file_type": "verilogSource"})
        opcoes["cocotb_module"] = pedido["modulos"]
        os.environ.update(
            {
                "PYTHONPATH": os.pathsep.join(pedido["pythonpath"]),
                "COCOTB_RESULTS_FILE": str(build / "results.xml"),
                "COCOTB_TOPLEVEL": topo,
                "TOPLEVEL_LANG": "verilog",
                "GPI_USERS": _cocotb_config("--libpython")
                + ";"
                + _cocotb_config("--pygpi-entry-point"),
            }
        )
        if pedido.get("filtro"):
            os.environ["COCOTB_TEST_FILTER"] = pedido["filtro"]
        topo = f"{topo} axil_onda"

    edam = {"name": pedido["nome"], "toplevel": topo, "files": arquivos, "flow_options": opcoes}
    fluxo = Sim(edam, str(build), verbose=True)
    signal.signal(signal.SIGALRM, _ao_estourar)
    signal.alarm(int(pedido["limite_s"]))
    try:
        print("@@axil:passo sim-compilar", flush=True)
        fluxo.configure()
        fluxo.build()
        print(f"@@axil:passo {pedido['passo_rodar']}", flush=True)
        fluxo.run()
    except _Limite:
        print(f"@@axil:limite {pedido['limite_s']:g}", flush=True)
        return 2
    except RuntimeError as erro:
        _corrigir_extensoes(build)
        print(f"@@axil:falha {erro}", flush=True)
        return 1
    finally:
        signal.alarm(0)
    _corrigir_extensoes(build)
    print("@@axil:sucesso", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1]))
