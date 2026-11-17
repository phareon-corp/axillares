"""Extrai a netlist para o esquemático e simula o circuito desenhado. Roda DENTRO da imagem.

Uso: python3 executar_esquema.py /trabalho/pedido.json

Modo "netlist" — quem lê o Verilog é o Yosys; este script só escolhe os comandos do nível:
  - rtl:     proc + opt — somadores, multiplexadores, registradores, como o código descreve;
  - portas:  synth + abc com portas genéricas — E, OU, OU exclusivo, flip-flops de 1 bit;
  - celulas: a netlist sintetizada pelo fluxo (.vg), com as células do PDK como caixas-pretas.
No nível de células, o KLayout lê o SPICE da biblioteca e diz quais transistores formam cada
célula usada (as células chamam os transistores como subcircuitos X; o delegado os transforma em
dispositivos MOS de quatro terminais).

A netlist de RTL e de portas também sai em Verilog (write_verilog -norename): é ela que se simula,
para cada fio do desenho ter um sinal com o mesmo nome na onda. No nível de células, simula-se a
própria .vg com os modelos Verilog das células do PDK.

Modo "simular" — Icarus Verilog (iverilog -g2012 + vvp) com o testbench que o Axillares gerou a
partir das entradas e do relógio escolhidos; grava a onda em VCD.

(As posições do desenho são calculadas pelo ELK, em layout_elk.js.)

Linhas "@@axil:…" marcam passos para o lado de fora.
"""

import json
import subprocess
import sys
from pathlib import Path


def _yosys(script: str, log: Path) -> None:
    resultado = subprocess.run(
        ["yosys", "-q", "-l", str(log), "-p", script], capture_output=True, text=True
    )
    if resultado.returncode != 0:
        sys.stdout.write(resultado.stdout + resultado.stderr)
        raise SystemExit(resultado.returncode)


def _leitura(pedido: dict) -> str:
    arquivos = " ".join(pedido["arquivos"])
    defines = " ".join(f"-D{d}" for d in pedido.get("defines", []))
    return f"read_verilog -sv {defines} {arquivos}; hierarchy -check -top {pedido['topo']}"


def _netlist(pedido: dict, saida: Path) -> None:
    nivel = pedido["nivel"]
    bruto = saida / "yosys.json"
    print(f"@@axil:passo esquema-{nivel}", flush=True)
    if nivel == "rtl":
        script = f"{_leitura(pedido)}; proc; opt -purge; clean -purge"
    elif nivel == "portas":
        script = (
            f"{_leitura(pedido)}; synth -flatten -top {pedido['topo']}; "
            "abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX; opt_clean -purge"
        )
    elif nivel == "celulas":
        script = (
            f"read_liberty -lib {pedido['liberty']}; read_verilog {pedido['netlist']}; "
            f"hierarchy -top {pedido['topo']}"
        )
    else:
        raise SystemExit(f"nível desconhecido: {nivel}")
    verilog = "" if nivel == "celulas" else f"; write_verilog -norename -noattr {saida}/netlist.v"
    _yosys(f"{script}; write_json {bruto}{verilog}", saida / "yosys.log")

    dados = json.loads(bruto.read_text(encoding="utf-8"))
    # as células da biblioteca entram como caixas-pretas: centenas de módulos sem conteúdo
    modulos = {
        nome: m
        for nome, m in dados.get("modules", {}).items()
        if not m.get("attributes", {}).get("blackbox")
    }
    (saida / "netlist.json").write_text(
        json.dumps({"creator": dados.get("creator", ""), "modules": modulos}), encoding="utf-8"
    )
    bruto.unlink()
    if nivel == "celulas" and pedido.get("spice"):
        tipos = sorted({c["type"] for m in modulos.values() for c in m["cells"].values()})
        _transistores(pedido["spice"], tipos, saida / "transistores.json")


def _transistores(spice: str, tipos: list[str], destino: Path) -> None:
    print("@@axil:passo esquema-transistores", flush=True)
    import klayout.db as db

    class Delegado(db.NetlistSpiceReaderDelegate):
        def wants_subcircuit(self, nome):
            return "FET" in nome.upper() or nome.upper().startswith("SG13_")

        def element(self, circuito, elemento, nome, modelo, valor, redes, parametros):
            if elemento != "X" or not self.wants_subcircuit(modelo):
                return super().element(circuito, elemento, nome, modelo, valor, redes, parametros)
            netlist = circuito.netlist()
            classe = netlist.device_class_by_name(modelo)
            if classe is None:
                classe = db.DeviceClassMOS4Transistor()
                classe.name = modelo
                netlist.add(classe)
            dispositivo = circuito.create_device(classe, nome)
            # SPICE: X<nome> dreno porta fonte corpo modelo
            for terminal, rede in zip(("D", "G", "S", "B"), redes, strict=False):
                dispositivo.connect_terminal(terminal, rede)
            for chave in ("W", "L"):
                dispositivo.set_parameter(chave, float(parametros.get(chave, 0.0)))
            return True

    netlist = db.Netlist()
    netlist.read(spice, db.NetlistSpiceReader(Delegado()))
    celulas = {}
    for tipo in tipos:
        circuito = netlist.circuit_by_name(tipo.upper()) or netlist.circuit_by_name(tipo)
        if circuito is None:
            continue
        dispositivos = []
        for d in circuito.each_device():
            classe = d.device_class()
            terminais = {
                t.name: d.net_for_terminal(t.id()).name
                for t in classe.terminal_definitions()
                if d.net_for_terminal(t.id()) is not None
            }
            dispositivos.append({
                "nome": d.expanded_name(), "modelo": classe.name, "terminais": terminais,
                "w": d.parameter("W"), "l": d.parameter("L"),
            })  # fmt: skip
        celulas[tipo] = {"pinos": [p.name() for p in circuito.each_pin()],
                         "dispositivos": dispositivos}  # fmt: skip
    destino.write_text(json.dumps(celulas), encoding="utf-8")


def _simular(pedido: dict, saida: Path) -> None:
    print("@@axil:passo esquema-simular", flush=True)
    defines = [f"-D{d}" for d in pedido.get("defines", [])]
    vvp = saida / "sim.vvp"
    compilar = subprocess.run(
        ["iverilog", "-g2012", *defines, "-o", str(vvp), pedido["tb"], *pedido["arquivos"]],
        capture_output=True, text=True,
    )  # fmt: skip
    if compilar.returncode != 0:
        linhas = [x for x in (compilar.stdout + compilar.stderr).splitlines()
                  if "warning" not in x.lower()]  # fmt: skip
        sys.stdout.write("\n".join(linhas[-30:]) + "\n")
        raise SystemExit(compilar.returncode)
    try:
        rodar = subprocess.run(
            ["vvp", "-n", str(vvp)], capture_output=True, text=True, cwd=saida,
            timeout=pedido.get("limite_s", 60),
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        print(f"@@axil:limite {pedido.get('limite_s', 60)}", flush=True)
        raise SystemExit(124) from None
    sys.stdout.write(rodar.stdout[-2000:])
    if rodar.returncode != 0:
        sys.stdout.write(rodar.stderr[-2000:])
        raise SystemExit(rodar.returncode)


def principal(caminho_pedido: str) -> int:
    pedido = json.loads(Path(caminho_pedido).read_text(encoding="utf-8"))
    saida = Path(pedido["saida"])
    saida.mkdir(parents=True, exist_ok=True)
    if pedido["modo"] == "simular":
        _simular(pedido, saida)
    else:
        _netlist(pedido, saida)
    print("@@axil:fim ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1]))
