"""Servidor de renderização de layout. Roda DENTRO da imagem, no KLayout em modo batch.

Uso: klayout -zz -r servidor_layout.py -rd gds=/gds/x.gds.gz -rd lyp=/caminho.lyp -rd saida=/saida

Lê pedidos em JSON, um por linha, na entrada padrão; responde um JSON por linha na saída padrão,
sempre prefixado por "@@axil " (o resto da saída é do KLayout e é ignorado). Quem lê e desenha
o GDS é o KLayout — o Axillares não tem leitor de GDS.

Opcionais: -rd celulas=<GDS completo das células padrão> (o GDS do fluxo traz as células só com
li1 e metais; lido por cima, o KLayout junta poço, difusão e poly a cada célula de mesmo nome) e
-rd regras=<json> (camadas de dispositivos e conectividade do PDK, de templates/explicacoes).

Pedidos:
  {"op": "info"}
  {"op": "render", "largura": 1600, "altura": 1000, "caixa": [x1, y1, x2, y2] | null,
   "ocultas": [indices], "fundo": "#08080B", "niveis": 99, "id": 7,
   "extras": "sem" | "so"}   — sem: só o layout; so: só destaques e ponteiras ligados
  {"op": "inspecionar", "x": 1.0, "y": 2.0, "raio": 0.05}
  {"op": "destaques", "ativos": ["pmos", "nmos", "poco_n", "diodo", "tap", "contato"]}
  {"op": "sondar", "x": 1.0, "y": 2.0, "raio": 0.05, "n": 1, "cor": "#FF4A1C"}
  {"op": "remover_sonda", "n": 1}

Destaques e ponteiras viram camadas extras do próprio layout ("axil:…"), desenhadas por cima.
"""

import itertools
import json
import sys

import pya

PREFIXO = "@@axil "
MARCA = "axil:"
# (título, cor, padrão de preenchimento do KLayout: 0 sólido, 1 só contorno)
DESTAQUES = {
    "pmos": ("Transistores PMOS", "#FFB020", 0),
    "nmos": ("Transistores NMOS", "#2EE89A", 0),
    "poco_n": ("Poço N (N-well)", "#8C9BFF", 1),
    "diodo": ("Diodos", "#FF5C61", 0),
    "tap": ("Taps (contato de poço)", "#D18CFF", 0),
    "contato": ("Contatos (licon)", "#4CC9FF", 0),
}


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
        if nome.startswith(MARCA):  # destaques e ponteiras não entram na lista de camadas
            it.next()
            continue
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


def _par(texto: str):
    camada, datatype = texto.split("/")
    return int(camada), int(datatype)


class Analise:
    """Regiões de dispositivos e conectividade, calculadas pelo KLayout sob demanda."""

    def __init__(self, vista, leiaute, topo, regras: dict) -> None:
        self.vista, self.leiaute, self.topo, self.regras = vista, leiaute, topo, regras
        self._regioes: dict = {}
        self._camadas_extras: dict = {}
        self._l2n = None
        self._condutores: dict = {}
        self._ligadas: set = set()

    def ligada(self, nome_camada: str) -> bool:
        return nome_camada[len(MARCA) :] in self._ligadas

    def regiao(self, fonte: str):
        if fonte not in self._regioes:
            li = self.leiaute.find_layer(*_par(fonte))
            self._regioes[fonte] = (
                pya.Region(self.topo.begin_shapes_rec(li)) if li is not None else pya.Region()
            )
        return self._regioes[fonte]

    def dispositivos(self) -> dict:
        d = self.regras.get("dispositivos", {})
        if not d:
            return {}
        if "portas" not in self._regioes:
            vazio = pya.Region()
            poco = self.regiao(d["poco_n"]) if "poco_n" in d else vazio
            portas = (self.regiao(d["porta"]) & self.regiao(d["difusao"])).merged()
            self._regioes["portas"] = portas
            self._regioes["pmos"] = (portas & poco).merged()
            self._regioes["nmos"] = (portas - poco).merged()
            self._regioes["poco_n"] = poco.merged()
            for chave in ("diodo", "tap", "contato"):
                self._regioes[chave] = self.regiao(d[chave]).merged() if chave in d else vazio
        return {k: self._regioes[k] for k in DESTAQUES}

    def camada_extra(self, nome: str, cor: str, padrao: int, largura: int):
        """Uma camada "axil:…" no layout e na lista de camadas da vista, por cima de todas."""
        if nome in self._camadas_extras:
            return self._camadas_extras[nome]
        numero = 9000 + len(self._camadas_extras)
        li = self.leiaute.insert_layer(pya.LayerInfo(numero, 0, MARCA + nome))
        props = pya.LayerPropertiesNode()
        props.source = f"{numero}/0@1"
        props.name = MARCA + nome
        props.fill_color = int(cor.lstrip("#"), 16)
        props.frame_color = int(cor.lstrip("#"), 16)
        props.dither_pattern = padrao
        props.width = largura
        props.visible = False
        self.vista.insert_layer(self.vista.begin_layers(), props)
        self._camadas_extras[nome] = li
        return li

    def mostrar(self, nome: str, visivel: bool) -> None:
        """Liga ou desliga um destaque/ponteira; quem desenha é o render com extras="so"."""
        if visivel:
            self._ligadas.add(nome)
        else:
            self._ligadas.discard(nome)

    def destaques(self, ativos: list) -> dict:
        regioes = self.dispositivos()
        contagem = {}
        for chave, (titulo, cor, padrao) in DESTAQUES.items():
            regiao = regioes.get(chave, pya.Region())
            contagem[chave] = {"titulo": titulo, "cor": cor, "quantos": regiao.count()}
            if chave in ativos and not regiao.is_empty():
                li = self.camada_extra(chave, cor, padrao, 3 if padrao == 1 else 1)
                if self.topo.shapes(li).is_empty():
                    self.topo.shapes(li).insert(regiao)
            if chave in self._camadas_extras:
                self.mostrar(chave, chave in ativos)
        return contagem

    # --- conectividade (ponteiras) -------------------------------------------------------

    def l2n(self):
        if self._l2n is not None:
            return self._l2n
        c = self.regras.get("conectividade", {})
        l2n = pya.LayoutToNetlist(pya.RecursiveShapeIterator(self.leiaute, self.topo, []))
        contador = [0]

        def camada(fontes: list):
            """make_layer já registra; a soma de várias camadas é região nova e precisa de
            registro próprio."""
            partes = []
            for fonte in fontes:
                li = self.leiaute.find_layer(*_par(fonte))
                if li is not None:
                    contador[0] += 1
                    partes.append(l2n.make_layer(li, f"c{contador[0]}"))
            if not partes:
                return None
            regiao = partes[0]
            for r in partes[1:]:
                regiao = regiao + r
            if len(partes) > 1:
                contador[0] += 1
                l2n.register(regiao, f"s{contador[0]}")
            return regiao

        porta = camada(c.get("porta", []))
        cadeia = []
        for fontes in c.get("cadeia", []):
            if fontes == ["sd"]:
                difusao = camada([self.regras["dispositivos"]["difusao"]])
                r = difusao
                if difusao is not None and porta is not None:
                    r = difusao - porta  # fonte e dreno, separados pela porta
                    l2n.register(r, "sd")
            else:
                r = camada(fontes)
            if r is None:
                continue
            cadeia.append((fontes, r))
            self._condutores[fontes[0]] = r
        for _f, r in cadeia:
            l2n.connect(r)
        for (_a, ra), (_b, rb) in itertools.pairwise(cadeia):
            l2n.connect(ra, rb)
        contato = self._condutores.get(c.get("cadeia", [[None], [None]])[1][0])
        if porta is not None:
            l2n.connect(porta)
            self._condutores["porta"] = porta
            if contato is not None:
                l2n.connect(porta, contato)
        tap = camada(c.get("tap", []))
        if tap is not None and contato is not None:
            l2n.connect(tap)
            l2n.connect(tap, contato)
        for rotulo, alvo in c.get("rotulos", {}).items():
            li = self.leiaute.find_layer(*_par(rotulo))
            destino = self._condutores.get(alvo)
            if li is not None and destino is not None:
                l2n.connect(destino, l2n.make_text_layer(li, "t" + rotulo.replace("/", "_")))
        l2n.extract_netlist()
        self._l2n = l2n
        return l2n

    def sondar(self, x: float, y: float, raio: float, n: int, cor: str) -> dict:
        l2n = self.l2n()
        c = self.regras.get("conectividade", {})
        no, camada_achada, caminho = None, None, []
        for fonte in c.get("ordem_sonda", []):
            chave = "porta" if fonte == c.get("porta", [None])[0] else fonte
            regiao = self._condutores.get(chave)
            if regiao is None:
                continue
            for dx, dy in ((0, 0), (raio, 0), (-raio, 0), (0, raio), (0, -raio)):
                caminho = []
                no = l2n.probe_net(regiao, pya.DPoint(x + dx, y + dy), caminho)
                if no is not None:
                    camada_achada = fonte
                    break
            if no is not None:
                break
        dispositivo = None
        for chave in ("pmos", "nmos"):
            regiao = self.dispositivos().get(chave)
            if regiao is not None:
                caixa = pya.DBox(x - raio, y - raio, x + raio, y + raio).to_itype(self.leiaute.dbu)
                tocadas = regiao.interacting(pya.Region(caixa))
                if not tocadas.is_empty():
                    b = tocadas.bbox().to_dtype(self.leiaute.dbu)
                    dispositivo = {"tipo": chave, "largura": b.width(), "altura": b.height()}
                    break
        if no is None:
            return {"x": x, "y": y, "n": n, "no": None, "dispositivo": dispositivo}
        # um nó dentro de uma célula vem nas coordenadas dela: a cadeia de instâncias o põe no
        # lugar certo do chip
        posicao = pya.DCplxTrans()
        for sub in caminho:
            posicao = posicao * sub.trans
        dbu = pya.CplxTrans(self.leiaute.dbu)
        para_topo = pya.ICplxTrans(dbu.inverted() * posicao * dbu)
        formas = pya.Region()
        camadas = {}
        for fontes_chave, regiao in self._condutores.items():
            r = l2n.shapes_of_net(no, regiao, True)
            if not r.is_empty():
                camadas[fontes_chave] = r.count()
                formas += r.transformed(para_topo)
        li = self.camada_extra(f"sonda{n}", cor, 0, 3)
        self.topo.shapes(li).clear()
        self.topo.shapes(li).insert(formas.merged())
        self.mostrar(f"sonda{n}", True)
        pinos = []
        for sp in no.each_subcircuit_pin():
            sub = sp.subcircuit()
            if not sp.pin().name() or sub.circuit_ref().name.startswith("VIA"):
                continue  # vias não têm pino com nome: não dizem nada a quem lê
            pinos.append(
                {
                    "celula": sub.circuit_ref().name,
                    "pino": sp.pin().name(),
                    "instancia": sub.expanded_name(),
                }
            )
            if len(pinos) >= 16:
                break
        nome = no.expanded_name()
        b = formas.bbox().to_dtype(self.leiaute.dbu)
        dentro = None
        if caminho:
            ultimo = caminho[-1]
            dentro = {"celula": ultimo.circuit_ref().name, "instancia": ultimo.expanded_name()}
        return {
            "dentro": dentro,
            "x": x,
            "y": y,
            "n": n,
            "no": nome,
            "interno": nome.startswith("$"),
            "camada": camada_achada,
            "camadas": camadas,
            "pinos": pinos,
            "caixa": [b.left, b.bottom, b.right, b.top],
            "dispositivo": dispositivo,
        }

    def remover_sonda(self, n: int) -> None:
        li = self._camadas_extras.get(f"sonda{n}")
        if li is not None:
            self.topo.shapes(li).clear()
            self.mostrar(f"sonda{n}", False)


def principal() -> None:
    gds = globals().get("gds")
    lyp = globals().get("lyp")
    saida = globals().get("saida", "/saida")

    vista = pya.LayoutView()
    vista.set_config("grid-visible", "false")
    vista.set_config("text-font", "1")
    vista.load_layout(gds, True)
    celulas = globals().get("celulas")
    if celulas:
        # mesmo nome de célula: o KLayout junta as formas (é o que o passo de escrita faz)
        vista.cellview(0).layout().read(celulas)
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

    regras = {}
    caminho_regras = globals().get("regras")
    if caminho_regras:
        with open(caminho_regras, encoding="utf-8") as arquivo:
            regras = json.load(arquivo)
    analise = Analise(vista, leiaute, topo, regras)

    responder({"op": "pronto", **info(), "analise": bool(regras)})
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
                extras = pedido.get("extras", "sem")
                it = vista.begin_layers()
                indice = 0
                while not it.at_end():
                    no = it.current()
                    if not no.has_children():
                        props = no.dup()
                        if no.name.startswith(MARCA):
                            props.visible = extras == "so" and analise.ligada(no.name)
                        else:
                            props.visible = extras != "so" and indice not in ocultas
                            indice += 1
                        vista.set_layer_properties(it, props)
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
            elif pedido.get("op") == "destaques":
                responder(
                    {
                        "op": "destaques",
                        "id": pedido.get("id"),
                        "contagem": analise.destaques(list(pedido.get("ativos", []))),
                    }
                )
            elif pedido.get("op") == "sondar":
                responder(
                    {
                        "op": "sondar",
                        "id": pedido.get("id"),
                        **analise.sondar(
                            float(pedido["x"]),
                            float(pedido["y"]),
                            float(pedido.get("raio", 0.05)),
                            int(pedido.get("n", 1)),
                            pedido.get("cor", "#FF4A1C"),
                        ),
                    }
                )
            elif pedido.get("op") == "remover_sonda":
                analise.remover_sonda(int(pedido.get("n", 1)))
                responder({"op": "remover_sonda", "id": pedido.get("id")})
            elif pedido.get("op") == "sair":
                break
        except Exception as erro:  # um pedido ruim não derruba o servidor
            responder({"op": "erro", "id": None, "mensagem": f"{type(erro).__name__}: {erro}"})


principal()
