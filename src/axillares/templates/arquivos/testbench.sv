// $nome — testbench: gera estímulos e confere as respostas em simulação. Não vira chip.
`timescale 1ns / 1ps

module $nome;
    logic clk = 1'b0;
    logic rst_n = 1'b0;

    always #5 clk = ~clk;  // relógio de 100 MHz

    initial begin
        $$dumpfile("$nome.vcd");
        $$dumpvars(0, $nome);
        #20 rst_n = 1'b1;
        #200 $$finish;
    end
endmodule
