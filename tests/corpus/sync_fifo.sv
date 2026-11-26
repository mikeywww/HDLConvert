`default_nettype none

// Single-clock FIFO. DEPTH must be at least two.
module sync_fifo #(
    parameter int unsigned DEPTH = 8,
    parameter int unsigned DATA_WIDTH = 8
) (
    input  logic clk, rst, push, pop,
    input  logic [DATA_WIDTH-1:0] din,
    output logic [DATA_WIDTH-1:0] dout,
    output logic full, empty
);
    localparam PTR_WIDTH = $clog2(DEPTH);
    logic [DATA_WIDTH-1:0] storage [0:DEPTH-1];
    logic [PTR_WIDTH-1:0] write_ptr, read_ptr;
    logic [PTR_WIDTH:0] count;

    assign full = count == DEPTH;
    assign empty = count == 0;
    assign dout = storage[read_ptr];

    always @(posedge clk) begin
        if (rst) begin
            write_ptr <= 0;
            read_ptr <= 0;
            count <= 0;
        end else begin
            if (push && !full) begin
                storage[write_ptr] <= din;
                if (write_ptr == DEPTH - 1) write_ptr <= 0;
                else write_ptr <= write_ptr + 1'b1;
            end
            if (pop && !empty) begin
                if (read_ptr == DEPTH - 1) read_ptr <= 0;
                else read_ptr <= read_ptr + 1'b1;
            end
            if (push && !full && !(pop && !empty)) count <= count + 1'b1;
            if (pop && !empty && !(push && !full)) count <= count - 1'b1;
        end
    end
endmodule

`default_nettype wire
