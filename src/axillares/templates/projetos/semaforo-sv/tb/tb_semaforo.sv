// Testbench em SystemVerilog: confere verde → amarelo → vermelho → verde.
`timescale 1ns/1ps
module tb_semaforo;
    logic clk = 0, rst_n = 0;
    logic verde, amarelo, vermelho;

    semaforo #(.T_VERDE(4), .T_AMARELO(2), .T_VERMELHO(3)) dut (.*);

    always #5 clk = ~clk;

    task automatic espera(int n);
        repeat (n) @(posedge clk);
        #1;
    endtask

    initial begin
        $dumpfile("tb_semaforo.vcd");
        $dumpvars(0, tb_semaforo);
        #12 rst_n = 1; #1;
        assert (verde)    else $fatal(1, "não começou no verde");
        espera(4); assert (amarelo)  else $fatal(1, "esperava amarelo");
        espera(2); assert (vermelho) else $fatal(1, "esperava vermelho");
        espera(3); assert (verde)    else $fatal(1, "esperava verde");
        $display("OK: verde → amarelo → vermelho → verde");
        $finish;
    end
endmodule
