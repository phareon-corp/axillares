# Axillares

Ambiente de desktop para projetar circuitos integrados com ferramentas abertas — **do Verilog ao
GDSII**, em português, para quem está aprendendo e para quem já projeta.

O Axillares prepara as ferramentas para você (uma imagem de contêiner com Yosys, OpenROAD,
SiliconCompiler, Icarus, Verilator, KLayout, Magic, Netgen e os PDKs sky130, gf180 e IHP), organiza
o projeto, executa o fluxo, guarda cada execução e explica cada passo e cada erro.

- **Editor** de Verilog/SystemVerilog com erros enquanto digita, formatação e lint explicado.
- **Fluxo ASIC** (síntese, posicionamento, roteamento, GDSII) e **FPGA** (iCEBreaker, ULX3S).
- **Execuções** guardadas com métricas, comparação entre execuções e falhas explicadas.
- **Layout** do chip dentro do app: camadas, transistores destacados, ponteiras em nós elétricos.
- **Simulação e testes** (testbench clássico ou cocotb) com as **ondas** desenhadas no app.
- **Esquemático** em notação técnica — RTL, portas lógicas, células do PDK e transistores — com o
  circuito **em funcionamento** (escolha entradas e relógio) e exportação em PNG, SVG, PDF ou
  prancha técnica com carimbo.

Tudo existe também como comando de terminal (`axil`).

## Requisitos

| | |
|---|---|
| Sistema | Linux x86-64 (testado no Fedora 44; outras distribuições com Python 3.12 funcionam) |
| Python | 3.12 ou mais novo — o `uv` baixa sozinho se não houver |
| Instalador | [`uv`](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Contêiner | **Podman** (recomendado) ou Docker |
| Disco | ~20 GB livres: a imagem de ferramentas baixa ~4 GB e ocupa ~15 GB |
| Rede | só na primeira vez (imagem de ferramentas e um componente de desenho de 1,6 MB) |

Instalar o Podman: Fedora `sudo dnf install podman` · Ubuntu/Debian `sudo apt install podman` ·
Arch `sudo pacman -S podman`. Com Docker, seu usuário precisa estar no grupo `docker`.

No Ubuntu/Debian, a interface gráfica (Qt 6) pede também: `sudo apt install libxcb-cursor0 libegl1`.

Opcionais, para abrir arquivos fora do app: KLayout (`flatpak install flathub de.klayout.KLayout`),
Surfer ou GTKWave.

## Instalação

### Opção 1 — direto do GitHub

```bash
uv tool install --python 3.12 "axillares[gui] @ git+https://github.com/phareon-corp/axillares"
```

O comando `axil` fica em `~/.local/bin` (garanta que essa pasta está no `PATH`; `uv tool
update-shell` faz isso).

### Opção 2 — clonando o repositório (com atalho no menu de aplicativos)

```bash
git clone https://github.com/phareon-corp/axillares.git
cd axillares
scripts/instalar.sh
```

O instalador coloca o comando `axil` em `~/.local/bin` e cria o atalho **Axillares** no menu, com
ícone.

### Preparar as ferramentas (uma vez)

```bash
axil ambiente instalar     # baixa a imagem de ferramentas, fixada por versão (~4 GB)
axil ambiente verificar    # confere cada ferramenta; diz o que fazer se faltar algo
```

Pela interface, a tela **Abertura** mostra a situação do ambiente e instala com um clique.

## Primeiros passos

Interface gráfica:

```bash
axil gui
```

Crie um projeto a partir de um modelo (portas lógicas, contador, semáforo), edite o Verilog e
execute a síntese ou o fluxo completo até o GDSII. Cada tela explica o que está acontecendo.

Terminal:

```bash
axil modelos                              # modelos de projeto disponíveis
axil novo meu-chip --modelo contador      # cria o projeto
cd meu-chip
axil executar sintese                     # síntese lógica (segundos)
axil executar gds                         # do RTL ao GDSII (menos de um minuto no contador)
axil runs                                 # execuções guardadas, com métricas
axil comparar penultima ultima            # o que mudou entre duas execuções
axil layout ultima -o chip.png            # o layout numa imagem
axil sim                                  # simula o testbench e grava a onda
axil teste                                # testes automáticos (cocotb)
axil onda --atividade                     # atividade de cada sinal na última onda
axil lint                                 # confere o RTL; cada aviso explicado
axil esquema                              # o circuito em notação técnica
axil esquema --simular --ciclos 10        # o circuito em funcionamento, ciclo a ciclo
axil esquema -n celulas -o chip.pdf --prancha A3   # prancha técnica com carimbo
axil executar fpga --placa icebreaker     # síntese, P&R e bitstream para FPGA
```

`axil --help` e `axil <comando> --help` mostram todas as opções.

## Atualizar e desinstalar

```bash
uv tool upgrade axillares        # instalado pela opção 1
git pull && scripts/instalar.sh  # instalado pela opção 2

uv tool uninstall axillares      # opção 1
scripts/instalar.sh --remover    # opção 2 (também remove o atalho)
podman rmi docker.io/hpretl/iic-osic-tools   # libera o espaço da imagem de ferramentas
```

## Licença

Apache-2.0 (arquivo `LICENSE`).

Componentes de terceiros: o editor Monaco (MIT, em `src/axillares/gui/editor/monaco/`), as fontes
Geist, Geist Mono, Bricolage Grotesque e Instrument Serif (SIL OFL 1.1, em
`src/axillares/gui/fontes/`). Baixados na primeira execução, nunca empacotados: a imagem de
ferramentas [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS), cada ferramenta sob a sua
licença, e o [elkjs](https://github.com/kieler/elkjs) (EPL-2.0), que monta o esquemático. As
ferramentas rodam como processos separados, dentro do contêiner.
