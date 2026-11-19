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
| Sistema | Linux x86-64 — Fedora, Ubuntu/Debian, Arch ou openSUSE |
| Permissão | `sudo`, só se faltar pacote do sistema |
| Disco | ~20 GB livres: a imagem de ferramentas baixa ~4 GB e ocupa ~15 GB |
| Rede | só na instalação |

Todo o resto — Podman, as bibliotecas do Qt 6, o `uv`, o Python 3.12, as ferramentas de EDA — o
instalador põe sozinho.

## Instalação

```bash
git clone https://github.com/phareon-corp/axillares.git
cd axillares
scripts/instalar.sh
```

Um comando, cinco etapas; rodar de novo é seguro, o que já está pronto é pulado:

1. **pacotes do sistema** que faltarem — Podman (com `uidmap`, para rodar sem root), `curl` e as
   bibliotecas que o Qt 6 carrega para abrir a janela — pelo gerenciador da distribuição (dnf, apt,
   pacman ou zypper). Só esta etapa pede a senha, e só se faltar algo;
2. o **`uv`**, se não houver (instalador oficial, em `~/.local/bin`);
3. o comando **`axil`** em `~/.local/bin`, com Python 3.12 e a interface gráfica;
4. o atalho **Axillares** no menu de aplicativos, com ícone;
5. as **ferramentas de EDA** — a imagem de contêiner fixada por digest (~4 GB, uma vez só) e o
   elkjs — e a conferência de cada ferramenta (`axil ambiente verificar`).

| Opção | O que faz |
|---|---|
| `--sem-ambiente` | não baixa a imagem agora; dá para baixar depois pela tela **Abertura** ou com `axil ambiente instalar` |
| `--sem-sistema` | não mexe nos pacotes do sistema (sem sudo) |
| `--editavel` | instala apontando para a pasta clonada (para desenvolver) |
| `--remover` | desinstala e tira o atalho |

Se o terminal disser "comando não encontrado" para `axil`, rode `uv tool update-shell` e abra um
terminal novo — o atalho do menu funciona de qualquer jeito.

### Sem clonar (avançado)

Quem já tem o `uv`, o Podman e as bibliotecas do Qt pode instalar só o programa:

```bash
uv tool install --python 3.12 "axillares[gui] @ git+https://github.com/phareon-corp/axillares"
axil atalho                 # entrada no menu de aplicativos
axil ambiente instalar      # ferramentas de EDA (~4 GB) e elkjs
```

Opcionais, para abrir arquivos fora do app: KLayout (`flatpak install flathub de.klayout.KLayout`),
Surfer ou GTKWave.

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

## Não aparece no menu ou não abre

1. **Não aparece no menu:** rode `axil atalho`. Se ainda não aparecer, saia da sessão e entre de
   novo (alguns ambientes só releem o menu no login).
2. **`axil: comando não encontrado`:** rode `uv tool update-shell` e abra um terminal novo (ou use
   `~/.local/bin/axil`).
3. **O ícone não abre nada:** rode `axil gui` num terminal para ver a mensagem. O mais comum é
   faltar biblioteca do Qt — rode `scripts/instalar.sh` de novo, que instala o que faltar; o próprio
   `axil gui` avisa quando ela falta.

## Atualizar e desinstalar

```bash
git pull && scripts/instalar.sh  # atualizar (clonado)
uv tool upgrade axillares        # atualizar (instalado sem clonar)

scripts/instalar.sh --remover    # desinstalar (também remove o atalho)
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
