"""Tela 8 — Esquema: o circuito em notação técnica, do RTL aos transistores.

Quatro níveis, os mesmos que o chip atravessa no fluxo:
  RTL           o que o código descreve: somadores, comparadores, multiplexadores, registradores;
  Portas        o mesmo circuito em portas lógicas e flip-flops de 1 bit (síntese genérica);
  Células       as células do PDK que a síntese do fluxo escolheu (a netlist .vg da execução);
  Transistores  dentro de cada célula, os pMOS e nMOS que a formam (SPICE da biblioteca).

À direita, "o que há no chip": o inventário do nível, com a explicação de cada componente, e o
detalhe do que foi escolhido no desenho — com o caminho de volta para a linha do Verilog.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from axillares.core import formato as fmt
from axillares.core.esquema import Bloco, Circuito, Esquema, Ligacao, Nivel
from axillares.core.modelos import Etapa
from axillares.core.simulacao_esquema import (
    Estimulo,
    LinhaDoTempo,
    estado_transistores,
    sugerir_estimulo,
)
from axillares.gui import tarefas
from axillares.gui import tema as t
from axillares.gui.componentes import botao, rotulo
from axillares.gui.componentes import segmentos as _segmentos
from axillares.gui.exportar_esquema import Carimbo, Pagina, exportar, exportar_caderno
from axillares.gui.sessao import Sessao
from axillares.gui.telas.esquema_exportar import DialogoExportar
from axillares.gui.telas.esquema_simulacao import PainelSimulacao
from axillares.gui.tema import Espaco, Papel
from axillares.gui.visor_esquema import EstadoSimulacao, VisorEsquema
from axillares.motor.esquema import GeradorEsquema

PAPEL_TIPO = Qt.ItemDataRole.UserRole
NIVEIS = (Nivel.RTL, Nivel.PORTAS, Nivel.CELULAS, Nivel.TRANSISTORES)
COMO_LER = {
    Nivel.RTL: "Cada bloco é uma operação do seu Verilog, do jeito que você escreveu: “+” é um "
    "somador, o trapézio é um multiplexador (um if/else ou ? :), a caixa com o triângulo é um "
    "registrador (um always @(posedge clk)). Fios grossos são barramentos — o número diz "
    "quantos bits. Clique num bloco e use “Ver no código” para achar a linha que o criou.",
    Nivel.PORTAS: "O mesmo circuito depois da síntese genérica: só portas lógicas (E, OU, OU "
    "exclusivo, inversores — a bolinha é a negação) e flip-flops de 1 bit. Sinais que vão a "
    "muitos lugares, como o relógio e o reset, aparecem como etiquetas com o nome, em vez de "
    "fios atravessando o desenho.",
    Nivel.CELULAS: "As células da biblioteca do PDK que a síntese do fluxo escolheu — é isto que "
    "vira desenho no layout. Portas complexas (a21oi, o21ai…) juntam várias portas numa célula "
    "só. A alimentação (VDD e terra) fica implícita. Duplo clique numa célula abre os "
    "transistores dela.",
    Nivel.TRANSISTORES: "Dentro de uma célula: pMOS em cima (com a bolinha na porta), ligados ao "
    "VDD, puxam a saída para 1; nMOS embaixo, ligados ao terra, puxam para 0. Transistores em "
    "série fazem E; em paralelo, OU. W/L é a largura e o comprimento do canal, em µm — quanto "
    "mais largo, mais corrente e mais rápido.",
}


class TelaEsquema(QWidget):
    def __init__(
        self,
        sessao: Sessao,
        fabrica_gerador: Callable[[], GeradorEsquema] | None = None,
    ) -> None:
        super().__init__()
        self.sessao = sessao
        self._fabrica = fabrica_gerador or GeradorEsquema
        self.nivel = Nivel.RTL
        self.circuitos: dict[Nivel, Circuito] = {}
        self.circuito: Circuito | None = None
        self.esquema: Esquema | None = None
        self._tarefa: tarefas.Tarefa | None = None
        self._celula_atual: str | None = None
        self._desatualizado = True
        # simulação
        self.estimulo: Estimulo | None = None
        self.linhas: dict[Nivel, LinhaDoTempo] = {}
        self._tarefa_sim: tarefas.Tarefa | None = None
        self._sim_pendente = False
        self._instancia: Bloco | None = None
        """Instância de célula cujos transistores se mostram na simulação."""
        self._espera_sim = QTimer(self)
        self._espera_sim.setSingleShot(True)
        self._espera_sim.setInterval(250)
        self._espera_sim.timeout.connect(self.simular)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._montar_barra())
        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.setHandleWidth(1)
        divisor.setChildrenCollapsible(False)
        self.pilha = QStackedWidget()
        self.visor = VisorEsquema()
        self.visor.bloco_escolhido.connect(self._bloco_escolhido)
        self.visor.rede_escolhida.connect(self._rede_escolhida)
        self.visor.entrar.connect(self._entrar)
        self.visor.entrada_clicada.connect(self._entrada_clicada)
        self.pilha.addWidget(self.visor)
        self.pilha.addWidget(self._montar_mensagem())
        esquerda = QWidget()
        col_esq = QVBoxLayout(esquerda)
        col_esq.setContentsMargins(0, 0, 0, 0)
        col_esq.setSpacing(0)
        col_esq.addWidget(self.pilha, 1)
        self.painel_sim = PainelSimulacao()
        self.painel_sim.hide()
        self.painel_sim.estimulo_mudou.connect(lambda _e: self._agendar_simulacao())
        self.painel_sim.tempo_mudou.connect(self._tempo_mudou)
        col_esq.addWidget(self.painel_sim)
        divisor.addWidget(esquerda)
        divisor.addWidget(self._montar_lateral())
        divisor.setStretchFactor(0, 1)
        divisor.setSizes([900, 340])
        raiz.addWidget(divisor, 1)

        sessao.projeto_mudou.connect(lambda _p: self._invalidar())
        sessao.execucao_concluida.connect(self._execucao_concluida)

    # --- montagem -----------------------------------------------------------------------------

    def _montar_barra(self) -> QWidget:
        barra = QFrame()
        barra.setProperty("tipo", "barra-abas")
        b = QHBoxLayout(barra)
        b.setContentsMargins(Espaco.M + 2, 6, Espaco.M, 6)
        b.setSpacing(Espaco.S)
        b.addWidget(rotulo("Esquema", Papel.ROTULO, "3"))
        niveis, self.grupo_nivel = _segmentos([(n.titulo, n) for n in NIVEIS], self.escolher_nivel)
        dicas = (
            "O circuito como o Verilog descreve",
            "Portas lógicas genéricas e flip-flops",
            "As células do PDK escolhidas pela síntese",
            "Os transistores de cada célula",
        )
        for i, dica in enumerate(dicas):
            self.grupo_nivel.button(i).setToolTip(dica)
        b.addLayout(niveis)
        b.addSpacing(Espaco.S)
        self.combo = QComboBox()
        self.combo.setFont(t.fonte(Papel.MONO))
        self.combo.setMinimumWidth(200)
        self.combo.activated.connect(self._escolheu_combo)
        b.addWidget(self.combo, 1)
        for texto, dica, acao in (
            ("−", "Afastar (−)", lambda: self.visor.zoom(1 / 1.4)),
            ("+", "Aproximar (+ ou roda do mouse)", lambda: self.visor.zoom(1.4)),
            ("Ajustar", "O circuito inteiro na tela (F)", lambda: self.visor.ajustar()),
        ):
            z = botao(texto, "compacto")
            z.setToolTip(dica)
            z.clicked.connect(acao)
            b.addWidget(z)
        b.addSpacing(Espaco.S)
        self.botao_simular = botao("▶ Simular", "compacto")
        self.botao_simular.setCheckable(True)
        self.botao_simular.setToolTip(
            "Ver o circuito funcionando: escolha as entradas e o relógio, e os fios ganham a cor "
            "do valor (verde 1, azul 0, vermelho X)"
        )
        self.botao_simular.toggled.connect(self._alternar_simulacao)
        b.addWidget(self.botao_simular)
        exportar = botao("Exportar…", "compacto")
        exportar.setToolTip("PNG, SVG, PDF ou prancha técnica com carimbo")
        exportar.clicked.connect(self.exportar)
        b.addWidget(exportar)
        regerar = botao("↻", "compacto")
        regerar.setToolTip("Gerar de novo")
        regerar.clicked.connect(lambda: self.gerar(forcar=True))
        b.addWidget(regerar)
        return barra

    def _montar_mensagem(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Espaco.XL, Espaco.XL, Espaco.XL, Espaco.XL)
        lay.addStretch(1)
        self.msg_titulo = rotulo("", Papel.TITULO)
        self.msg_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_texto = rotulo("", Papel.CORPO, "2")
        self.msg_texto.setWordWrap(True)
        self.msg_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_texto.setMaximumWidth(620)
        lay.addWidget(self.msg_titulo)
        lay.addSpacing(Espaco.S)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(self.msg_texto)
        linha.addStretch(1)
        lay.addLayout(linha)
        lay.addSpacing(Espaco.M)
        acoes = QHBoxLayout()
        acoes.addStretch(1)
        self.msg_acao = botao("Sintetizar  ▸", "primario")
        self.msg_acao.clicked.connect(lambda: self.sessao.executar(Etapa.SINTESE))
        acoes.addWidget(self.msg_acao)
        acoes.addStretch(1)
        lay.addLayout(acoes)
        lay.addStretch(2)
        return w

    def _montar_lateral(self) -> QWidget:
        lateral = QFrame()
        lateral.setProperty("tipo", "lateral-editor")
        lateral.setMinimumWidth(280)
        col = QVBoxLayout(lateral)
        col.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        conteudo = QWidget()
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(Espaco.M, Espaco.M, Espaco.M, Espaco.M)
        lay.setSpacing(Espaco.S)

        lay.addWidget(rotulo("O que há no chip", Papel.EYEBROW, "acento"))
        self.origem = rotulo("", Papel.PEQUENO, "3")
        self.origem.setWordWrap(True)
        lay.addWidget(self.origem)
        self.resumo = rotulo("", Papel.CORPO_FORTE)
        self.resumo.setWordWrap(True)
        lay.addWidget(self.resumo)
        self.inventario = QTreeWidget()
        self.inventario.setHeaderHidden(True)
        self.inventario.setRootIsDecorated(False)
        self.inventario.setColumnCount(2)
        self.inventario.setFont(t.fonte(Papel.MONO))
        self.inventario.setMinimumHeight(160)
        self.inventario.itemClicked.connect(self._item_inventario)
        self.inventario.itemDoubleClicked.connect(self._item_inventario_duplo)
        lay.addWidget(self.inventario, 1)

        lay.addSpacing(Espaco.S)
        lay.addWidget(rotulo("Escolhido", Papel.EYEBROW, "acento"))
        self.det_titulo = rotulo("Clique num bloco ou num fio.", Papel.CORPO_FORTE)
        self.det_titulo.setWordWrap(True)
        self.det_texto = rotulo("", Papel.PEQUENO, "2")
        self.det_texto.setWordWrap(True)
        self.det_texto.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.det_titulo)
        lay.addWidget(self.det_texto)
        acoes = QHBoxLayout()
        self.botao_codigo = botao("Ver no código ↗", "compacto")
        self.botao_codigo.clicked.connect(self._ver_no_codigo)
        self.botao_transistores = botao("Ver transistores", "compacto")
        self.botao_transistores.clicked.connect(self._ver_transistores)
        acoes.addWidget(self.botao_codigo)
        acoes.addWidget(self.botao_transistores)
        acoes.addStretch(1)
        lay.addLayout(acoes)
        self.botao_codigo.hide()
        self.botao_transistores.hide()

        lay.addSpacing(Espaco.S)
        lay.addWidget(rotulo("Como ler", Papel.EYEBROW, "3"))
        self.como_ler = QLabel()
        self.como_ler.setFont(t.fonte(Papel.PEQUENO))
        self.como_ler.setWordWrap(True)
        self.como_ler.setProperty("tom", "2")
        lay.addWidget(self.como_ler)
        lay.addStretch(1)
        rolagem.setWidget(conteudo)
        col.addWidget(rolagem)
        return lateral

    # --- ciclo --------------------------------------------------------------------------------

    def ao_mostrar(self) -> None:
        if self._desatualizado or self.nivel_base() not in self.circuitos:
            self.gerar()

    def _invalidar(self) -> None:
        self.circuitos.clear()
        self.linhas.clear()
        self.estimulo = None
        self._instancia = None
        self.circuito = self.esquema = None
        self._celula_atual = None
        self._desatualizado = True
        self.visor.mostrar(None)
        if self.isVisible():
            self.gerar()

    def _execucao_concluida(self, *_args) -> None:
        # uma síntese nova muda a netlist de células; o RTL pode ter mudado no editor
        self.circuitos.clear()
        self.linhas.clear()
        self._desatualizado = True
        if self.isVisible():
            self.gerar()

    def nivel_base(self) -> Nivel:
        return Nivel.CELULAS if self.nivel is Nivel.TRANSISTORES else self.nivel

    def escolher_nivel(self, nivel: Nivel) -> None:
        self.nivel = nivel
        self.grupo_nivel.button(NIVEIS.index(nivel)).setChecked(True)
        self.como_ler.setText(COMO_LER[nivel])
        if self.nivel_base() in self.circuitos:
            self._mostrar_circuito(self.circuitos[self.nivel_base()])
            if self.botao_simular.isChecked():
                if self.nivel_base() in self.linhas:
                    self._tempo_mudou(self.painel_sim.t_ns())
                else:
                    self.simular()
        else:
            self.gerar()

    def gerar(self, forcar: bool = False) -> None:
        projeto = self.sessao.projeto
        if projeto is None:
            return
        self.como_ler.setText(COMO_LER[self.nivel])
        if forcar:
            self.circuitos.clear()
            self.linhas.clear()
        if self._tarefa is not None and self._tarefa.rodando:
            return
        nivel = self.nivel_base()
        self._mensagem("Gerando o esquemático…", "Preparando a imagem de ferramentas.", acao=False)
        gerador = self._fabrica()
        if forcar:
            cache = projeto.raiz / ".axil" / "cache" / "esquema"
            for arquivo in list(cache.glob("*.json")) + list(cache.glob("*.vcd")) \
                    if cache.is_dir() else []:  # fmt: skip
                arquivo.unlink(missing_ok=True)

        def rodar(trab) -> Circuito:
            return gerador.gerar(projeto, nivel, ao_progresso=trab.linha.emit)

        tarefa = tarefas.Tarefa(rodar, self)
        tarefa.linha.connect(lambda texto: self.msg_texto.setText(f"{texto}…"))
        tarefa.concluido.connect(lambda c, n=nivel: self._gerado(n, c))
        tarefa.falhou.connect(self._falhou)
        self._tarefa = tarefa
        tarefa.iniciar()

    def _gerado(self, nivel: Nivel, circuito: Circuito) -> None:
        self.circuitos[nivel] = circuito
        self.linhas.pop(nivel, None)
        self._desatualizado = False
        if nivel is self.nivel_base():
            self._mostrar_circuito(circuito)
            if self.botao_simular.isChecked():
                self._preparar_estimulo()
                self.simular()
        else:
            self.gerar()

    def _falhou(self, mensagem: str) -> None:
        sem_netlist = "Ainda não há netlist de células" in mensagem
        titulo = "Falta sintetizar" if sem_netlist else "Não deu para gerar o esquemático"
        self._mensagem(titulo, mensagem, acao=sem_netlist)

    def _mensagem(self, titulo: str, texto: str, acao: bool) -> None:
        self.msg_titulo.setText(titulo)
        self.msg_texto.setText(texto)
        self.msg_acao.setVisible(acao)
        self.pilha.setCurrentIndex(1)

    # --- exibição -----------------------------------------------------------------------------

    def _mostrar_circuito(self, circ: Circuito) -> None:
        self.circuito = circ
        self.combo.blockSignals(True)
        self.combo.clear()
        if self.nivel is Nivel.TRANSISTORES:
            if not circ.esquemas_celulas:
                self._mensagem(
                    "Sem transistores",
                    "O perfil não traz o SPICE das células deste PDK, ou a netlist não usa "
                    "células conhecidas.",
                    acao=False,
                )
                self.combo.blockSignals(False)
                return
            usos = Counter(b.tipo for b in circ.modulos[circ.topo].componentes())
            for tipo in sorted(
                circ.esquemas_celulas, key=lambda x: len(circ.celulas[x].transistores)
            ):
                n = len(circ.celulas[tipo].transistores)
                self.combo.addItem(f"{tipo}  ·  {n} transistores  ·  {usos[tipo]}× no chip", tipo)
            escolhida = self._celula_atual if self._celula_atual in circ.esquemas_celulas else None
            if escolhida is None:  # a célula lógica mais usada
                escolhida = max(
                    circ.esquemas_celulas,
                    key=lambda x: (len(circ.celulas[x].transistores) <= 12, usos[x]),
                )
            self.combo.blockSignals(False)
            self._mostrar_celula(escolhida)
            return
        for nome in sorted(circ.modulos, key=lambda n: (n != circ.topo, n)):
            self.combo.addItem(nome + ("  (topo)" if nome == circ.topo else ""), nome)
        self.combo.setCurrentIndex(0)
        self.combo.setVisible(True)
        self.combo.blockSignals(False)
        self._mostrar_modulo(circ.topo)

    def _escolheu_combo(self, _i: int) -> None:
        dado = self.combo.currentData()
        if dado is None:
            return
        if self.nivel is Nivel.TRANSISTORES:
            self._mostrar_celula(dado)
        else:
            self._mostrar_modulo(dado)

    def _mostrar_modulo(self, nome: str) -> None:
        circ = self.circuito
        if circ is None or nome not in circ.modulos:
            return
        esq = circ.modulos[nome]
        self.esquema = esq
        self._preencher_inventario(circ, nome)
        if not esq.posicionado:
            self._mensagem("Grande demais para desenhar", f"Este módulo tem {len(esq.blocos)} "
                           "blocos — o desenho ficaria ilegível. O inventário ao lado mostra tudo "
                           "o que há nele; módulos menores podem ser vistos pela lista acima.",
                           acao=False)  # fmt: skip
            return
        self.pilha.setCurrentIndex(0)
        self.visor.mostrar(esq)
        self._limpar_detalhe()

    def _mostrar_celula(self, tipo: str) -> None:
        circ = self.circuito
        if circ is None or tipo not in circ.esquemas_celulas:
            return
        self._celula_atual = tipo
        esq = circ.esquemas_celulas[tipo]
        cel = circ.celulas[tipo]
        self.esquema = esq
        self.inventario.clear()
        self.origem.setText(f"{tipo} · {circ.origem}")
        self.resumo.setText(f"{len(cel.transistores)} transistores: {cel.n_pmos} pMOS e "
                            f"{cel.n_nmos} nMOS")  # fmt: skip
        for item_tipo, quantos in (("pMOS", cel.n_pmos), ("nMOS", cel.n_nmos)):
            if quantos:
                self.inventario.addTopLevelItem(QTreeWidgetItem([f"{quantos} ×", item_tipo]))
        usos = sum(1 for b in circ.modulos[circ.topo].componentes() if b.tipo == tipo)
        if usos:
            self.inventario.addTopLevelItem(QTreeWidgetItem([f"{usos} ×", "instâncias no chip"]))
        self._ajustar_colunas()
        self.pilha.setCurrentIndex(0)
        self.visor.mostrar(esq)
        self._limpar_detalhe()

    def _preencher_inventario(self, circ: Circuito, modulo: str) -> None:
        self.inventario.clear()
        self.origem.setText(f"{self.nivel.titulo} · {circ.origem}")
        itens = circ.inventario(modulo)
        componentes = sum(i.quantidade for i in itens if i.simbolo != "fisica")
        partes = [f"{fmt.numero(componentes, 0)} componentes"]
        bits = circ.bits_de_registro(modulo)
        if bits:
            partes.append(f"{fmt.numero(bits, 0)} bits de registro")
        transistores = circ.transistores(modulo)
        if transistores:
            p, n = transistores
            partes.append(f"{fmt.numero(p + n, 0)} transistores ({p} pMOS, {n} nMOS)")
            if fisicos := circ.transistores_fisicos(modulo):
                partes.append(f"{fmt.numero(fisicos, 0)} deles em células físicas")
        self.resumo.setText(" · ".join(partes))
        for item in itens:
            nome = item.rotulo or item.tipo.lstrip("$")
            if item.simbolo == "fisica":
                nome += "  (física)"
            elif item.transistores:
                nome += f"  · {item.transistores} T"
            linha = QTreeWidgetItem([f"{item.quantidade} ×", nome])
            linha.setData(0, PAPEL_TIPO, item.tipo)
            linha.setToolTip(1, f"{item.tipo}\n{item.explicacao}")
            self.inventario.addTopLevelItem(linha)
        self._ajustar_colunas()

    def _ajustar_colunas(self) -> None:
        self.inventario.resizeColumnToContents(0)

    # --- escolha ------------------------------------------------------------------------------

    def _limpar_detalhe(self) -> None:
        self.det_titulo.setText("Clique num bloco ou num fio.")
        self.det_texto.setText("")
        self.botao_codigo.hide()
        self.botao_transistores.hide()
        self._escolhido: Bloco | None = None

    def _bloco_escolhido(self, bloco: Bloco | None) -> None:
        if bloco is None:
            self._limpar_detalhe()
            return
        self._escolhido = bloco
        titulo = bloco.rotulo if bloco.simbolo in {"entrada", "saida", "bidir", "rotulo"} \
            else bloco.tipo  # fmt: skip
        self.det_titulo.setText(titulo)
        linhas = []
        if bloco.explicacao:
            linhas.append(bloco.explicacao)
        if bloco.instancia and bloco.instancia != titulo:
            linhas.append(f"<b>instância</b> {bloco.instancia}")
        pinos = [p for p in bloco.pinos if p.lado != "c"]
        if pinos and bloco.simbolo not in {"entrada", "saida", "rotulo", "constante"}:
            descr = ", ".join(
                f"{p.nome}{f'[{p.largura}]' if p.largura > 1 else ''}"
                f"{'→' if p.direcao == 'saida' else ''}"
                for p in pinos
            )
            linhas.append(f"<b>pinos</b> {descr}")
        for chave, valor in bloco.detalhes.items():
            if chave == "instância":
                continue
            linhas.append(f"<b>{chave}</b> {valor}")
        if self.circuito and bloco.tipo in self.circuito.celulas:
            cel = self.circuito.celulas[bloco.tipo]
            linhas.append(f"<b>transistores</b> {len(cel.transistores)} ({cel.n_pmos} pMOS, "
                          f"{cel.n_nmos} nMOS)")  # fmt: skip
        if bloco.origem:
            linhas.append(f"<b>origem</b> {bloco.origem.arquivo}, linha {bloco.origem.linha}")
        self.det_texto.setText("<br>".join(linhas))
        self.botao_codigo.setVisible(bloco.origem is not None)
        self.botao_transistores.setVisible(
            self.nivel is Nivel.CELULAS
            and self.circuito is not None
            and bloco.tipo in self.circuito.esquemas_celulas
        )

    def _rede_escolhida(self, lig: Ligacao | None) -> None:
        if lig is None:
            return
        self.det_titulo.setText(f"Fio {lig.rede}" if lig.rede else "Fio")
        largura = "1 bit" if lig.largura == 1 else f"barramento de {lig.largura} bits"
        destinos = sum(1 for x in (self.esquema.ligacoes if self.esquema else []) if x.de == lig.de)
        self.det_texto.setText(f"{largura} · sai de {lig.de[1]} e chega a {destinos} pino(s). "
                               "A rede inteira fica destacada.")  # fmt: skip
        self.botao_codigo.hide()
        self.botao_transistores.hide()

    def _item_inventario(self, item: QTreeWidgetItem, _coluna: int) -> None:
        tipo = item.data(0, PAPEL_TIPO)
        self.visor.destacar_tipo(tipo)
        if tipo and self.esquema is not None:
            primeiro = next((b for b in self.esquema.blocos if b.tipo == tipo), None)
            if primeiro is not None:
                self.visor.escolher(primeiro, centralizar=False)
                self._bloco_escolhido(primeiro)

    def _item_inventario_duplo(self, item: QTreeWidgetItem, _coluna: int) -> None:
        tipo = item.data(0, PAPEL_TIPO)
        if tipo and self.circuito and tipo in self.circuito.esquemas_celulas:
            self._celula_atual = tipo
            self.escolher_nivel(Nivel.TRANSISTORES)

    def _entrar(self, bloco: Bloco) -> None:
        circ = self.circuito
        if circ is None:
            return
        if bloco.simbolo == "modulo" and bloco.tipo in circ.modulos:
            self.combo.setCurrentIndex(max(0, self.combo.findData(bloco.tipo)))
            self._mostrar_modulo(bloco.tipo)
        elif bloco.tipo in circ.esquemas_celulas:
            self._celula_atual = bloco.tipo
            self._instancia = bloco
            self.escolher_nivel(Nivel.TRANSISTORES)

    def _ver_no_codigo(self) -> None:
        bloco = getattr(self, "_escolhido", None)
        projeto = self.sessao.projeto
        if bloco is None or bloco.origem is None or projeto is None:
            return
        caminho = projeto.raiz / bloco.origem.arquivo
        self.sessao.pedir_tela.emit("editar", (str(caminho), bloco.origem.linha))

    def _ver_transistores(self) -> None:
        bloco = getattr(self, "_escolhido", None)
        if bloco is not None:
            self._entrar(bloco)

    # --- simulação ---------------------------------------------------------------------------

    def _alternar_simulacao(self, ligada: bool) -> None:
        self.painel_sim.setVisible(ligada)
        self.botao_simular.setText("■ Parar" if ligada else "▶ Simular")
        if not ligada:
            self.painel_sim.pausar()
            self.visor.definir_estado(None)
            return
        if self.nivel_base() not in self.circuitos:
            return  # simula quando o circuito chegar
        self._preparar_estimulo()
        if self.nivel_base() in self.linhas:
            self._tempo_mudou(self.painel_sim.t_ns())
        else:
            self.simular()

    def _preparar_estimulo(self) -> None:
        circ = self.circuitos.get(self.nivel_base())
        if circ is None:
            return
        esq = circ.modulos[circ.topo]
        if self.estimulo is None:
            self.estimulo = sugerir_estimulo(esq)
        self.painel_sim.configurar(esq.portas, self.estimulo)

    def _agendar_simulacao(self) -> None:
        self.linhas.clear()
        self._espera_sim.start()

    def simular(self) -> None:
        projeto = self.sessao.projeto
        nivel = self.nivel_base()
        circ = self.circuitos.get(nivel)
        if projeto is None or circ is None or self.estimulo is None:
            return
        if self._tarefa_sim is not None and self._tarefa_sim.rodando:
            self._sim_pendente = True
            return
        self._sim_pendente = False
        gerador = self._fabrica()
        estimulo = Estimulo(self.estimulo.ciclos, self.estimulo.periodo_ns, self.estimulo.relogio,
                            {k: dict(v) for k, v in self.estimulo.entradas.items()})  # fmt: skip
        self.painel_sim.definir_situacao("simulando…")

        def rodar(trab) -> LinhaDoTempo:
            return gerador.simular(projeto, circ, estimulo, ao_progresso=trab.linha.emit)

        tarefa = tarefas.Tarefa(rodar, self)
        tarefa.concluido.connect(lambda linha, n=nivel: self._simulado(n, linha))
        tarefa.falhou.connect(self._simulacao_falhou)
        self._tarefa_sim = tarefa
        tarefa.iniciar()

    def _simulado(self, nivel: Nivel, linha: LinhaDoTempo) -> None:
        self.linhas[nivel] = linha
        self.painel_sim.definir_situacao(f"Icarus · {self.nivel_base().titulo.lower()}")
        if self._sim_pendente:
            self.simular()
        if nivel is self.nivel_base() and self.botao_simular.isChecked():
            self._tempo_mudou(self.painel_sim.t_ns())

    def _simulacao_falhou(self, mensagem: str) -> None:
        self.painel_sim.definir_situacao("a simulação falhou")
        self.visor.definir_estado(None)
        self.det_titulo.setText("A simulação não rodou")
        self.det_texto.setText(mensagem.replace("\n", "<br>"))
        if self._sim_pendente:
            self.simular()

    def estado_atual(self) -> EstadoSimulacao | None:
        if not self.botao_simular.isChecked():
            return None
        linha = self.linhas.get(self.nivel_base())
        if linha is None:
            return None
        t_ns = self.painel_sim.t_ns()
        estado = EstadoSimulacao(linha, t_ns)
        if self.nivel is Nivel.TRANSISTORES and self.circuito and self._celula_atual:
            cel = self.circuito.celulas.get(self._celula_atual)
            instancia = self._instancia
            topo = self.circuito.modulos[self.circuito.topo]
            if instancia is None or instancia.tipo != self._celula_atual:
                instancia = next((b for b in topo.blocos if b.tipo == self._celula_atual), None)
            if cel is not None and instancia is not None:
                pinos = {pn.nome: linha.valor(pn.bits, t_ns) for pn in instancia.pinos}
                estado.transistores = estado_transistores(cel, pinos)
                self.det_titulo.setText(f"Instância {instancia.instancia or instancia.id}")
                valores = ", ".join(f"{k}={v}" for k, v in pinos.items())
                self.det_texto.setText(
                    f"Pinos no instante {t_ns:g} ns: {valores}. Canal grosso e verde: o "
                    "transistor conduz; tracejado: cortado. É o estado lógico, não elétrico."
                )
        return estado

    def _tempo_mudou(self, _t_ns: float) -> None:
        self.visor.definir_estado(self.estado_atual())

    def _entrada_clicada(self, bloco: Bloco) -> None:
        self.painel_sim.alternar_entrada(bloco.instancia or bloco.rotulo)

    # --- exportação ---------------------------------------------------------------------------

    def _carimbo(self) -> Carimbo:
        projeto = self.sessao.projeto
        esq = self.esquema
        return Carimbo(
            titulo=(esq.nome if esq else ""),
            projeto=projeto.nome if projeto else "",
            nivel=self.nivel.titulo,
            descricao=projeto.projeto.descricao if projeto else "",
            pdk=(self.circuito.pdk if self.circuito and self.circuito.pdk
                 else (projeto.asic.pdk.value if projeto else "")),
        )  # fmt: skip

    def exportar(self) -> None:
        if self.esquema is None or not self.esquema.posicionado:
            return
        estado = self.estado_atual()
        dialogo = DialogoExportar(self._carimbo(), estado is not None, self)
        if dialogo.exec() != DialogoExportar.DialogCode.Accepted:
            return
        opcoes = dialogo.opcoes()
        projeto = self.sessao.projeto
        nome = self.esquema.nome.split("__")[-1]
        sufixo = "caderno" if dialogo.tipo == "caderno" else self.nivel.value
        sugestao = (projeto.raiz if projeto else Path.home()) / f"{nome}-{sufixo}{dialogo.extensao}"
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar esquemático", str(sugestao), f"*{dialogo.extensao}"
        )
        if not caminho:
            return
        destino = Path(caminho)
        if destino.suffix.lower() != dialogo.extensao:
            destino = destino.with_suffix(dialogo.extensao)
        estado = estado if dialogo.simulacao.isChecked() else None
        if dialogo.tipo == "caderno":
            exportar_caderno(self.paginas_do_caderno(estado), destino, opcoes)
        else:
            exportar(self.esquema, destino, opcoes, estado)

    def paginas_do_caderno(self, estado: EstadoSimulacao | None = None) -> list[Pagina]:
        """Todos os módulos do nível e, se houver, os transistores de cada célula usada."""
        circ = self.circuito
        if circ is None:
            return []
        paginas = [Pagina(esq, f"{self.nivel_base().titulo} · {nome}",
                          estado if nome == circ.topo else None, titulo=nome)
                   for nome, esq in sorted(circ.modulos.items(),
                                           key=lambda x: (x[0] != circ.topo, x[0]))
                   if esq.posicionado]  # fmt: skip
        for tipo, esq in sorted(circ.esquemas_celulas.items()):
            if esq.posicionado:
                paginas.append(Pagina(esq, "Transistores", titulo=tipo))
        return paginas
