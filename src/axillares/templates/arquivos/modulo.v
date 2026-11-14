// $nome — descreva aqui o que este módulo faz.
module $nome (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] entrada,
    output reg  [7:0] saida
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            saida <= 8'd0;
        end else begin
            saida <= entrada;
        end
    end

endmodule
