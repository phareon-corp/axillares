"""Servidor de renderização de layout. Roda DENTRO da imagem, no KLayout em modo batch.

Uso: klayout -zz -r servidor_layout.py -rd gds=/gds/x.gds.gz -rd lyp=/caminho.lyp -rd saida=/saida

Lê pedidos em JSON, um por linha, na entrada padrão; responde um JSON por linha na saída padrão,
sempre prefixado por "@@axil " (o resto da saída é do KLayout e é ignorado). Quem lê e desenha
o GDS é o KLayout — o Axillares não tem leitor de GDS.

Pedidos:
  {"op": "info"}
  {"op": "render", "largura": 1600, "altura": 1000, "caixa": [x1, y1, x2, y2] | null,
   "ocultas": [indices], "fundo": "#08080B", "niveis": 99, "id": 7}
"""

import json
import sys

import pya

PREFIXO = "@@axil "


def responder(dados: dict) -> None:
    sys.stdout.write(PREFIXO + json.dumps(dados) + "\n")
    sys.stdout.flush()


def camadas(vista) -> list:
    lista = []
    it = vista.begin_layers()
    indice = 0
    while not it.at_end():
        no = it.current()
        if no.has_children():
            it.next()
            continue
        nome = no.name or f"{no.source_layer}/{no.source_datatype}"
        lista.append(
            {
                "indice": indice,
                "nome": nome,
                "fonte": f"{no.source_layer}/{no.source_datatype}",
                "cor": "#%06X" % (no.fill_color & 0xFFFFFF),
                "visivel": bool(no.visible),
            }
        )
        indice += 1
        it.next()
    return lista


def tipo_da(forma) -> str:
    if forma.is_path():
        return "caminho"
    return "texto" if forma.is_text() else "polígono"


def inspecionar(vista, leiaute, topo, x: float, y: float, raio: float) -> dict:
    """O que existe no ponto (x, y) µm: as células (instâncias) e as formas por camada."""
    caixa = pya.DBox(x - raio, y - raio, x + raio, y + raio)
    caixa_dbu = caixa.to_itype(leiaute.dbu)
    celulas = []
    for inst in topo.each_overlapping_inst(caixa_dbu):
        b = inst.dbbox()
        nome_inst = ""
        prop = inst.property(1) or inst.property("INST_NAME") if inst.has_prop_id() else None
        if prop:
            nome_inst = str(prop)
        celulas.append(
            {
                "celula": inst.cell.name,
                "instancia": nome_inst,
                "caixa": [b.left, b.bottom, b.right, b.top],
            }
        )
    nomes = {}
    it = vista.begin_layers()
    while not it.at_end():
        no = it.current()
        if not no.has_children():
            nomes[(no.source_layer, no.source_datatype)] = no.name
        it.next()
    formas = []
    for li in leiaute.layer_indexes():
        info = leiaute.get_info(li)
        rec = topo.begin_shapes_rec_touching(li, caixa)
        while not rec.at_end() and len(formas) < 40:
            forma = rec.shape()
            b = forma.dbbox().transformed(rec.dtrans())
            formas.append(
                {
                    "camada": nomes.get(
                        (info.layer, info.datatype), f"{info.layer}/{info.datatype}"
                    ),
                    "fonte": f"{info.layer}/{info.datatype}",
                    "caixa": [b.left, b.bottom, b.right, b.top],
                    "tipo": "caminho"
                    if forma.is_path()
                    else ("texto" if forma.is_text() else "polígono"),
                    "texto": forma.text_string if forma.is_text() else "",
                    "celula": rec.cell().name,
                }
            )
            rec.next()
    celulas.sort(key=lambda c: (c["caixa"][2] - c["caixa"][0]) * (c["caixa"][3] - c["caixa"][1]))
    return {"x": x, "y": y, "celulas": celulas[:8], "formas": formas}


def principal() -> None:
    gds = globals().get("gds")
    lyp = globals().get("lyp")
    saida = globals().get("saida", "/saida")

    vista = pya.LayoutView()
    vista.set_config("grid-visible", "false")
    vista.set_config("text-font", "1")
    vista.load_layout(gds, True)
    if lyp:
        vista.load_layer_props(lyp)
    vista.max_hier()
    vista.zoom_fit()
    leiaute = vista.cellview(0).layout()
    topo = vista.cellview(0).cell
    caixa_total = topo.dbbox()
    # Só as camadas que têm geometria neste GDS: a lista do PDK tem centenas.
    usadas = set()
    for li in leiaute.layer_indexes():
        if not topo.bbox_per_layer(li).empty():
            info = leiaute.get_info(li)
            usadas.add(f"{info.layer}/{info.datatype}")

    def info() -> dict:
        todas = camadas(vista)
        return {
            "celula": topo.name,
            "caixa": [caixa_total.left, caixa_total.bottom, caixa_total.right, caixa_total.top],
            "dbu": leiaute.dbu,
            "camadas": [c for c in todas if c["fonte"] in usadas],
        }

    responder({"op": "pronto", **info()})
    contador = 0
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            pedido = json.loads(linha)
            if pedido.get("op") == "info":
                responder({"op": "info", **info()})
            elif pedido.get("op") == "render":
                ocultas = set(pedido.get("ocultas", []))
                it = vista.begin_layers()
                indice = 0
                while not it.at_end():
                    no = it.current()
                    if not no.has_children():
                        props = no.dup()
                        props.visible = indice not in ocultas
                        vista.set_layer_properties(it, props)
                        indice += 1
                    it.next()
                vista.set_config("background-color", pedido.get("fundo", "#000000"))
                vista.max_hier_levels = int(pedido.get("niveis", 99))
                caixa = pedido.get("caixa")
                alvo = pya.DBox(*caixa) if caixa else caixa_total
                largura, altura = int(pedido["largura"]), int(pedido["altura"])
                contador += 1
                arquivo = f"{saida}/vista-{contador % 4}.png"
                vista.save_image_with_options(arquivo, largura, altura, 0, 0, 0, alvo, False)
                # a caixa realmente mostrada (a proporção da imagem manda)
                razao = max(alvo.width() / largura, alvo.height() / altura)
                cx, cy = alvo.center().x, alvo.center().y
                mostrada = [
                    cx - razao * largura / 2,
                    cy - razao * altura / 2,
                    cx + razao * largura / 2,
                    cy + razao * altura / 2,
                ]
                responder(
                    {
                        "op": "render",
                        "id": pedido.get("id"),
                        "arquivo": arquivo,
                        "caixa": mostrada,
                        "largura": largura,
                        "altura": altura,
                    }
                )
            elif pedido.get("op") == "inspecionar":
                responder(
                    {
                        "op": "inspecionar",
                        "id": pedido.get("id"),
                        **inspecionar(
                            vista,
                            leiaute,
                            topo,
                            pedido["x"],
                            pedido["y"],
                            float(pedido.get("raio", 0.05)),
                        ),
                    }
                )
            elif pedido.get("op") == "sair":
                break
        except Exception as erro:  # um pedido ruim não derruba o servidor
            responder({"op": "erro", "id": None, "mensagem": f"{type(erro).__name__}: {erro}"})


principal()
