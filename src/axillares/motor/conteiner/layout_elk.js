// Posiciona grafos com o ELK (Eclipse Layout Kernel, elkjs). Roda DENTRO da imagem, no Node dela.
// Uso: node layout_elk.js /elk/elk.bundled.js /trabalho/grafos.json /trabalho/saida.json
// Entrada: {"nome": grafoELK, ...}; saída: {"nome": grafoELK com x, y, seções e junções}.
"use strict";
const fs = require("fs");
const ELK = require(process.argv[2]);
const grafos = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const elk = new ELK();
(async () => {
  const saida = {};
  for (const [nome, grafo] of Object.entries(grafos)) {
    process.stdout.write(`@@axil:passo esquema-posicoes ${nome}\n`);
    saida[nome] = await elk.layout(grafo);
  }
  fs.writeFileSync(process.argv[4], JSON.stringify(saida));
  process.stdout.write("@@axil:fim ok\n");
})().catch((erro) => {
  process.stdout.write(`ERRO ELK: ${erro && erro.message ? erro.message : erro}\n`);
  process.exit(1);
});
