// Verilog-2001 register bank with a legacy compound-assignment extension.
module reg_bank (
    input clk, rst,
    input [1:0] request,
    input [31:0] bus_data,
    input [4:0] low_base, high_base,
    output reg [15:0] q
);
    reg [1:0] byte_enable;

    // Request bit 1 takes precedence over request bit 0.
    always @(*) begin
        casez (request)
            2'b1?: byte_enable = 2'b10;
            2'b01: byte_enable = 2'b01;
            default: byte_enable = 2'b00;
        endcase
    end

    always @(posedge clk) begin
        if (rst) q[7:0] <= 8'b0;
        else if (byte_enable[0]) q[7:0] <= bus_data[low_base +: 8];
    end

    always @(posedge clk) begin
        if (rst) q[15:8] = 8'b0;
        else if (byte_enable[1]) q[15:8] += bus_data[high_base -: 8];
    end
endmodule
