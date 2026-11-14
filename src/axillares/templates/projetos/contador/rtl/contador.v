// Contador síncrono de N bits com habilitação e reset assíncrono ativo em nível baixo.
module contador #(
    parameter N = 8
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         en,
    output reg  [N-1:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= {N{1'b0}};
        else if (en)
            q <= q + 1'b1;
    end
endmodule
