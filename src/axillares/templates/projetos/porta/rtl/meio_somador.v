// Meio-somador: soma dois bits.
//
//   a b | soma vai_um
//   0 0 |   0     0
//   0 1 |   1     0
//   1 0 |   1     0
//   1 1 |   0     1
//
// "assign" descreve uma ligação contínua: a saída muda assim que as entradas mudam.
// A síntese vai trocar cada operador por uma célula da biblioteca do PDK (uma porta XOR
// e uma porta AND) — veja quais na netlist depois de executar a síntese.
module meio_somador (
    input  wire a,
    input  wire b,
    output wire soma,
    output wire vai_um
);
    assign soma   = a ^ b;   // OU exclusivo
    assign vai_um = a & b;   // E
endmodule
