// Testbench clássico do contador: reset, contagem com en=1 e pausa com en=0.
// Rode com “axil sim” e abra a onda: clk, rst_n, en e q mudando no tempo.
`timescale 1ns/1ps
module tb_contador;
    reg clk = 0, rst_n = 0, en = 0;
    wire [7:0] q;

    contador #(.N(8)) dut (.clk(clk), .rst_n(rst_n), .en(en), .q(q));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_contador.vcd");
        $dumpvars(0, tb_contador);
        #12 rst_n = 1;
        en = 1;
        repeat (10) @(posedge clk);
        #1 en = 0;  // depois da borda: mudar junto com ela seria uma corrida
        repeat (3) @(posedge clk);
        #1;
        if (q !== 8'd10) begin
            $display("FALHOU: q = %0d, esperado 10", q);
            $fatal(1);
        end
        $display("OK: q = %0d", q);
        $finish;
    end
endmodule
