// $nome — descreva aqui o que este módulo faz.
module $nome (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [7:0] entrada,
    output logic [7:0] saida
);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            saida <= 8'd0;
        end else begin
            saida <= entrada;
        end
    end

endmodule
