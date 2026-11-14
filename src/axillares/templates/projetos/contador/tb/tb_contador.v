// Testbench clássico do contador: reset, contagem com en=1 e pausa com en=0.
// Simulação e ondas chegam ao Axillares na fase F4 (axil sim); por ora, o arquivo já existe
// para você rodar à mão: iverilog -o tb tb/tb_contador.v rtl/contador.v && vvp tb
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
        en = 0;
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
