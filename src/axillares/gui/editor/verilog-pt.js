// Conteúdo didático do editor (dado, não lógica): dicas e trechos de Verilog em português.
window.DIDATICA = {
  "dicas": {
    "module": "**module** — começa a descrição de um bloco de hardware: um nome e a lista de portas (os fios que entram e saem). Termina em `endmodule`.",
    "endmodule": "**endmodule** — fecha o módulo.",
    "input": "**input** — porta de entrada: um sinal que vem de fora do módulo.",
    "output": "**output** — porta de saída: um sinal que o módulo entrega para fora.",
    "inout": "**inout** — porta bidirecional, que pode entrar ou sair (raro em projetos simples).",
    "wire": "**wire** — um fio: não guarda valor, só liga coisas. Recebe valor por `assign` ou pela saída de outro módulo.",
    "reg": "**reg** — variável que recebe valor dentro de um `always`. Apesar do nome, só vira registrador (flip-flop) se for atribuída numa borda de relógio.",
    "logic": "**logic** (SystemVerilog) — substitui `wire` e `reg`: serve para os dois casos.",
    "assign": "**assign** — ligação contínua: a saída acompanha as entradas o tempo todo. Gera lógica combinacional (portas), sem memória.\n\n`assign soma = a ^ b;`",
    "always": "**always** — um bloco que reage a eventos. Com `@(posedge clk)` vira lógica sequencial (flip-flops); com `@(*)` vira lógica combinacional.",
    "always_ff": "**always_ff** (SystemVerilog) — bloco sequencial: o compilador confere que ele realmente vira flip-flops.",
    "always_comb": "**always_comb** (SystemVerilog) — bloco combinacional: o compilador confere que não sobra memória por engano (latch).",
    "posedge": "**posedge** — borda de subida: o instante em que o sinal vai de 0 para 1. `@(posedge clk)` = \"a cada pulso do relógio\".",
    "negedge": "**negedge** — borda de descida: o sinal vai de 1 para 0. Em `negedge rst_n`, o reset age assim que o pino baixa (reset assíncrono, ativo em nível baixo).",
    "begin": "**begin … end** — agrupa vários comandos num bloco, como chaves `{ }` em outras linguagens.",
    "end": "**end** — fecha um `begin`.",
    "if": "**if / else** — escolha: na síntese vira um multiplexador (o circuito calcula os dois lados e escolhe um).",
    "else": "**else** — o outro lado do `if`.",
    "case": "**case** — escolha entre vários valores; o jeito clássico de escrever máquinas de estado. Termine com `default` para não criar latch.",
    "endcase": "**endcase** — fecha o `case`.",
    "default": "**default** — o que fazer quando nenhum caso do `case` bate. Evita memória acidental (latch).",
    "parameter": "**parameter** — uma constante que pode ser trocada de fora, ao instanciar o módulo: `contador #(.N(16)) c(...)`.",
    "localparam": "**localparam** — constante interna, que não pode ser trocada de fora. Ótima para nomear estados.",
    "initial": "**initial** — roda uma vez, no início da simulação. Só serve em testbench: não vira hardware.",
    "for": "**for** — repetição. Na síntese o laço é desdobrado: cada volta vira hardware de verdade.",
    "generate": "**generate** — gera várias cópias de hardware em tempo de elaboração.",
    "integer": "**integer** — variável inteira de 32 bits; comum em testbench e em laços.",
    "timescale": "**`timescale** — unidade de tempo da simulação e sua precisão: `1ns/1ps`. Só afeta simulação.",
    "clk": "**clk** — por convenção, o relógio: o sinal que bate o ritmo de todos os flip-flops.",
    "rst_n": "**rst_n** — reset ativo em nível baixo (o `_n` indica isso): com 0, o circuito volta ao estado inicial.",
    "typedef": "**typedef** (SystemVerilog) — dá nome a um tipo: `typedef logic [7:0] byte_t;`. Combina com `enum` e `struct`.",
    "enum": "**enum** (SystemVerilog) — uma lista de nomes para valores, ideal para estados: `typedef enum logic [1:0] {OCIOSO, RODANDO} estado_t;`. O simulador mostra os nomes nas ondas.",
    "struct": "**struct** (SystemVerilog) — agrupa vários campos num só sinal. Com `packed`, vira um vetor de bits contínuo e é sintetizável.",
    "packed": "**packed** — os campos ficam colados num vetor de bits; é o que a síntese entende para `struct` e `union`.",
    "unique": "**unique case** (SystemVerilog) — promete que exatamente um item casa. O simulador avisa se nenhum ou mais de um casar; a síntese pode simplificar a lógica.",
    "priority": "**priority case/if** (SystemVerilog) — o primeiro que casa vence, e o simulador avisa se nenhum casar.",
    "bit": "**bit** (SystemVerilog) — só 0 ou 1, sem X nem Z. Bom em testbench; no circuito prefira `logic`, que mostra X quando algo não foi iniciado.",
    "int": "**int** (SystemVerilog) — inteiro de 32 bits com sinal, de 2 estados. Comum em laços e testbench.",
    "byte": "**byte** (SystemVerilog) — inteiro de 8 bits com sinal, de 2 estados.",
    "package": "**package** (SystemVerilog) — guarda tipos, constantes e funções para vários módulos usarem com `import nome_pkg::*;`.",
    "endpackage": "**endpackage** — fecha o package.",
    "import": "**import** — traz o conteúdo de um package: `import cores_pkg::*;`.",
    "interface": "**interface** (SystemVerilog) — um feixe de fios com nome, para ligar módulos sem repetir a lista de portas.",
    "modport": "**modport** — dentro de uma interface, diz a direção de cada fio do ponto de vista de um lado (mestre, escravo…).",
    "function": "**function** — cálculo combinacional reutilizável; devolve um valor e não consome tempo.",
    "task": "**task** — como função, mas pode esperar tempo (`#10`, `@(posedge clk)`). Mais comum em testbench.",
    "automatic": "**automatic** — cada chamada tem as próprias variáveis (como em software). Use em funções recursivas e em testbench.",
    "always_latch": "**always_latch** (SystemVerilog) — bloco que *deve* gerar latch. Raro e quase sempre evitável.",
    "genvar": "**genvar** — o índice de um `for` dentro de `generate`.",
    "assert": "**assert** — confere uma condição na simulação e reclama se for falsa. Não vira hardware.",
    "signed": "**signed** — o vetor representa números com sinal (complemento de 2): comparações e deslocamentos passam a respeitar o sinal.",
    "inside": "**inside** (SystemVerilog) — testa se um valor está num conjunto: `if (op inside {SOMA, SUB})`."
  },
  "operadores": {
    "<=": "**<=** — atribuição *não bloqueante*: use em blocos com relógio. Todos os flip-flops atualizam juntos, no fim do pulso.",
    "=": "**=** — atribuição *bloqueante*: use em lógica combinacional e em testbench. Acontece na ordem em que está escrita."
  },
  "trechos": [
    {
      "rotulo": "modulo",
      "detalhe": "esqueleto de um módulo",
      "texto": "module ${1:nome} (\n    input  wire       clk,\n    input  wire       rst_n,\n    input  wire [7:0] ${2:entrada},\n    output reg  [7:0] ${3:saida}\n);\n    $0\nendmodule"
    },
    {
      "rotulo": "always relógio",
      "detalhe": "lógica sequencial: flip-flops com reset",
      "texto": "always @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n        ${1:q} <= ${2:0};\n    end else begin\n        $0\n    end\nend"
    },
    {
      "rotulo": "always combinacional",
      "detalhe": "lógica combinacional dentro de um bloco",
      "texto": "always @(*) begin\n    $0\nend"
    },
    {
      "rotulo": "assign",
      "detalhe": "ligação contínua (portas lógicas)",
      "texto": "assign ${1:saida} = ${2:a} & ${3:b};"
    },
    {
      "rotulo": "case estados",
      "detalhe": "máquina de estados",
      "texto": "case (${1:estado})\n    ${2:OCIOSO}: begin\n        $0\n    end\n    default: ${1:estado} <= ${2:OCIOSO};\nendcase"
    },
    {
      "rotulo": "localparam estados",
      "detalhe": "nomes para os estados",
      "texto": "localparam ${1:OCIOSO} = 2'd0;\nlocalparam ${2:RODANDO} = 2'd1;"
    },
    {
      "rotulo": "if else",
      "detalhe": "escolha (vira multiplexador)",
      "texto": "if (${1:condicao}) begin\n    $2\nend else begin\n    $0\nend"
    },
    {
      "rotulo": "testbench relógio",
      "detalhe": "gera um relógio na simulação",
      "texto": "always #${1:5} clk = ~clk;"
    },
    {
      "rotulo": "always_ff",
      "detalhe": "SystemVerilog: flip-flops com reset",
      "texto": "always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n        ${1:q} <= '0;\n    end else begin\n        $0\n    end\nend"
    },
    {
      "rotulo": "always_comb",
      "detalhe": "SystemVerilog: lógica combinacional conferida",
      "texto": "always_comb begin\n    ${1:saida} = ${2:'0};\n    $0\nend"
    },
    {
      "rotulo": "enum estados",
      "detalhe": "SystemVerilog: tipo com os nomes dos estados",
      "texto": "typedef enum logic [${1:1}:0] {\n    ${2:OCIOSO},\n    ${3:RODANDO}\n} ${4:estado_t};\n\n${4:estado_t} estado, proximo;"
    },
    {
      "rotulo": "máquina de estados SV",
      "detalhe": "SystemVerilog: registrador de estado + próximo estado",
      "texto": "always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) estado <= ${1:OCIOSO};\n    else        estado <= proximo;\nend\n\nalways_comb begin\n    proximo = estado;\n    unique case (estado)\n        ${1:OCIOSO}: if (${2:comecar}) proximo = ${3:RODANDO};\n        ${3:RODANDO}: $0\n        default: proximo = ${1:OCIOSO};\n    endcase\nend"
    },
    {
      "rotulo": "struct packed",
      "detalhe": "SystemVerilog: campos num só vetor",
      "texto": "typedef struct packed {\n    logic [7:0] ${1:dado};\n    logic       ${2:valido};\n} ${3:pacote_t};"
    },
    {
      "rotulo": "package",
      "detalhe": "SystemVerilog: tipos e constantes compartilhados",
      "texto": "package ${1:nome}_pkg;\n    localparam int ${2:LARGURA} = ${3:8};\n    $0\nendpackage"
    },
    {
      "rotulo": "modulo sv",
      "detalhe": "SystemVerilog: esqueleto de módulo com parâmetro",
      "texto": "module ${1:nome} #(\n    parameter int LARGURA = ${2:8}\n) (\n    input  logic               clk,\n    input  logic               rst_n,\n    input  logic [LARGURA-1:0] ${3:entrada},\n    output logic [LARGURA-1:0] ${4:saida}\n);\n    $0\nendmodule"
    },
    {
      "rotulo": "instância",
      "detalhe": "usar um módulo dentro de outro",
      "texto": "${1:modulo} ${2:u_nome} (\n    .clk   (clk),\n    .rst_n (rst_n),\n    .${3:porta} (${4:sinal})\n);"
    },
    {
      "rotulo": "function",
      "detalhe": "cálculo combinacional reutilizável",
      "texto": "function automatic logic [${1:7}:0] ${2:nome}(input logic [${1:7}:0] ${3:x});\n    return ${3:x}$0;\nendfunction"
    }
  ]
}
;
