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
    "rst_n": "**rst_n** — reset ativo em nível baixo (o `_n` indica isso): com 0, o circuito volta ao estado inicial."
  },
  "operadores": {
    "<=": "**<=** — atribuição *não bloqueante*: use em blocos com relógio. Todos os flip-flops atualizam juntos, no fim do pulso.",
    "=": "**=** — atribuição *bloqueante*: use em lógica combinacional e em testbench. Acontece na ordem em que está escrita."
  },
  "trechos": [
    {"rotulo": "modulo", "detalhe": "esqueleto de um módulo", "texto": "module ${1:nome} (\n    input  wire       clk,\n    input  wire       rst_n,\n    input  wire [7:0] ${2:entrada},\n    output reg  [7:0] ${3:saida}\n);\n    $0\nendmodule"},
    {"rotulo": "always relógio", "detalhe": "lógica sequencial: flip-flops com reset", "texto": "always @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n        ${1:q} <= ${2:0};\n    end else begin\n        $0\n    end\nend"},
    {"rotulo": "always combinacional", "detalhe": "lógica combinacional dentro de um bloco", "texto": "always @(*) begin\n    $0\nend"},
    {"rotulo": "assign", "detalhe": "ligação contínua (portas lógicas)", "texto": "assign ${1:saida} = ${2:a} & ${3:b};"},
    {"rotulo": "case estados", "detalhe": "máquina de estados", "texto": "case (${1:estado})\n    ${2:OCIOSO}: begin\n        $0\n    end\n    default: ${1:estado} <= ${2:OCIOSO};\nendcase"},
    {"rotulo": "localparam estados", "detalhe": "nomes para os estados", "texto": "localparam ${1:OCIOSO} = 2'd0;\nlocalparam ${2:RODANDO} = 2'd1;"},
    {"rotulo": "if else", "detalhe": "escolha (vira multiplexador)", "texto": "if (${1:condicao}) begin\n    $2\nend else begin\n    $0\nend"},
    {"rotulo": "testbench relógio", "detalhe": "gera um relógio na simulação", "texto": "always #${1:5} clk = ~clk;"}
  ]
}
;
