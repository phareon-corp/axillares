// Semáforo: uma máquina de estados finitos (FSM).
//
// O circuito guarda em que estado está (VERDE, AMARELO ou VERMELHO) e conta quantos
// pulsos de relógio já passou nele. Quando o tempo do estado acaba, passa ao próximo.
//
//   VERDE --(T_VERDE)--> AMARELO --(T_AMARELO)--> VERMELHO --(T_VERMELHO)--> VERDE
module semaforo #(
    parameter T_VERDE    = 20,
    parameter T_AMARELO  = 5,
    parameter T_VERMELHO = 15
) (
    input  wire clk,
    input  wire rst_n,
    output wire verde,
    output wire amarelo,
    output wire vermelho
);
    localparam VERDE    = 2'd0;
    localparam AMARELO  = 2'd1;
    localparam VERMELHO = 2'd2;

    reg [1:0] estado;
    reg [4:0] tempo;    // pulsos de relógio passados no estado atual

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            estado <= VERDE;
            tempo  <= 5'd0;
        end else begin
            tempo <= tempo + 5'd1;
            case (estado)
                VERDE:    if (tempo == T_VERDE - 1)    begin estado <= AMARELO;  tempo <= 5'd0; end
                AMARELO:  if (tempo == T_AMARELO - 1)  begin estado <= VERMELHO; tempo <= 5'd0; end
                VERMELHO: if (tempo == T_VERMELHO - 1) begin estado <= VERDE;    tempo <= 5'd0; end
                default:  begin estado <= VERDE; tempo <= 5'd0; end
            endcase
        end
    end

    // As saídas dependem só do estado (máquina de Moore).
    assign verde    = (estado == VERDE);
    assign amarelo  = (estado == AMARELO);
    assign vermelho = (estado == VERMELHO);
endmodule
