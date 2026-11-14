// Semáforo em SystemVerilog: enum para os estados, always_ff e always_comb.
module semaforo #(
    parameter int T_VERDE    = 20,
    parameter int T_AMARELO  = 5,
    parameter int T_VERMELHO = 15
) (
    input  logic clk,
    input  logic rst_n,
    output logic verde,
    output logic amarelo,
    output logic vermelho
);
    typedef enum logic [1:0] {
        VERDE,
        AMARELO,
        VERMELHO
    } estado_t;
    estado_t estado, proximo;
    logic [4:0] tempo;
    logic fim;

    always_comb begin
        unique case (estado)
            VERDE:    fim = (tempo == 5'(T_VERDE - 1));
            AMARELO:  fim = (tempo == 5'(T_AMARELO - 1));
            VERMELHO: fim = (tempo == 5'(T_VERMELHO - 1));
            default:  fim = 1'b1;
        endcase
        unique case (estado)
            VERDE:   proximo = AMARELO;
            AMARELO: proximo = VERMELHO;
            default: proximo = VERDE;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            estado <= VERDE;
            tempo  <= '0;
        end else if (fim) begin
            estado <= proximo;
            tempo  <= '0;
        end else begin
            tempo <= tempo + 1'b1;
        end
    end

    assign verde    = (estado == VERDE);
    assign amarelo  = (estado == AMARELO);
    assign vermelho = (estado == VERMELHO);
endmodule
