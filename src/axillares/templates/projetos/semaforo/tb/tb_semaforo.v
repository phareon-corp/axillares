// Testbench do semáforo: confere a sequência verde → amarelo → vermelho → verde.
`timescale 1ns/1ps
module tb_semaforo;
    reg clk = 0, rst_n = 0;
    wire verde, amarelo, vermelho;

    semaforo #(.T_VERDE(4), .T_AMARELO(2), .T_VERMELHO(3)) dut (
        .clk(clk), .rst_n(rst_n), .verde(verde), .amarelo(amarelo), .vermelho(vermelho));

    always #5 clk = ~clk;

    task espera(input integer n); repeat (n) @(posedge clk); #1; endtask

    initial begin
        $dumpfile("tb_semaforo.vcd");
        $dumpvars(0, tb_semaforo);
        #12 rst_n = 1; #1;
        if (!verde) begin $display("FALHOU: não começou no verde"); $fatal(1); end
        espera(4); if (!amarelo)  begin $display("FALHOU: esperava amarelo");  $fatal(1); end
        espera(2); if (!vermelho) begin $display("FALHOU: esperava vermelho"); $fatal(1); end
        espera(3); if (!verde)    begin $display("FALHOU: esperava verde");    $fatal(1); end
        $display("OK: verde → amarelo → vermelho → verde");
        $finish;
    end
endmodule
