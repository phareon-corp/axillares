// Testbench do meio-somador: percorre a tabela-verdade inteira.
`timescale 1ns/1ps
module tb_meio_somador;
    reg a, b;
    wire soma, vai_um;
    integer i;

    meio_somador dut (.a(a), .b(b), .soma(soma), .vai_um(vai_um));

    initial begin
        $dumpfile("tb_meio_somador.vcd");
        $dumpvars(0, tb_meio_somador);
        for (i = 0; i < 4; i = i + 1) begin
            {a, b} = i[1:0];
            #5;
            if ({vai_um, soma} !== a + b) begin
                $display("FALHOU: %b + %b deu %b%b", a, b, vai_um, soma);
                $fatal(1);
            end
        end
        $display("OK: tabela-verdade conferida");
        $finish;
    end
endmodule
