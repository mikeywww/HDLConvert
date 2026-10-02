`timescale 1ns / 1ps

// A logical frame contains PACKETS_PER_FRAME packets and each packet contains
// PACKET_WORDS accepted words. rx_packet_start marks a packet's first word.
// rx_frame_start marks a frame's first word and closes the preceding frame.
// Two RAM banks permit receive and transmit activity to overlap.
module aurora_packet_bridge #(
    parameter int unsigned DATA_WIDTH        = 64,
    parameter int unsigned KEEP_WIDTH        = DATA_WIDTH / 8,
    parameter int unsigned PACKET_WORDS      = 100,
    parameter int unsigned PACKETS_PER_FRAME = 10,
    parameter int unsigned BANK_ADDR_WIDTH   = 10,
    parameter int unsigned RAM_ADDR_WIDTH    = BANK_ADDR_WIDTH + 1
) (
    input  logic                      user_clk,
    input  logic                      reset_n,
    input  logic [    DATA_WIDTH-1:0] m_axi_rx_tdata,
    input  logic [    KEEP_WIDTH-1:0] m_axi_rx_tkeep,
    input  logic                      m_axi_rx_tlast,
    input  logic                      m_axi_rx_tvalid,
    input  logic                      rx_packet_start,
    input  logic                      rx_frame_start,
    output logic [    DATA_WIDTH-1:0] s_axi_tx_tdata,
    output logic [    KEEP_WIDTH-1:0] s_axi_tx_tkeep,
    output logic                      s_axi_tx_tlast,
    output logic                      s_axi_tx_tvalid,
    input  logic                      s_axi_tx_tready,
    output logic                      ram_wr_en,
    output logic [RAM_ADDR_WIDTH-1:0] ram_wr_addr,
    output logic [    DATA_WIDTH-1:0] ram_wr_data,
    output logic                      ram_rd_en,
    output logic [RAM_ADDR_WIDTH-1:0] ram_rd_addr,
    input  logic [    DATA_WIDTH-1:0] ram_rd_data,
    output logic                      rx_frame_valid,
    output logic                      tx_packet_start,
    output logic                      tx_frame_start,
    output logic                      tx_frame_done,
    output logic                      rx_length_error,
    output logic                      rx_keep_error,
    output logic                      rx_control_error,
    output logic                      rx_overflow,
    output logic                      buffer_valid,
    output logic                      tx_busy
);

    localparam int unsigned FRAME_WORDS = PACKET_WORDS * PACKETS_PER_FRAME;
    localparam int unsigned FRAME_COUNT_WIDTH = $clog2(FRAME_WORDS + 2);
    localparam int unsigned PACKET_COUNT_WIDTH = $clog2(PACKETS_PER_FRAME + 2);
    localparam int unsigned PACKET_WORD_COUNT_WIDTH = $clog2(PACKET_WORDS + 2);
    localparam logic [KEEP_WIDTH-1:0] KEEP_ALL = '1;

    typedef enum logic [1:0] {
        TX_IDLE,
        TX_LOAD,
        TX_SEND
    } tx_state_t;
    tx_state_t                               tx_state;

    logic      [                        1:0] bank_ready;
    logic                                    write_bank;
    logic                                    tx_bank;
    logic                                    frame_seen;
    logic                                    capture_active;
    logic                                    frame_error_latched;
    logic                                    packet_closed;

    logic      [      FRAME_COUNT_WIDTH-1:0] rx_frame_word_count;
    logic      [     PACKET_COUNT_WIDTH-1:0] rx_packet_count;
    logic      [PACKET_WORD_COUNT_WIDTH-1:0] rx_packet_word_count;
    logic      [      FRAME_COUNT_WIDTH-1:0] tx_frame_word_index;
    logic      [     PACKET_COUNT_WIDTH-1:0] tx_packet_index;
    logic      [PACKET_WORD_COUNT_WIDTH-1:0] tx_packet_word_index;

    logic                                    boundary_bank;
    logic                                    boundary_bank_available;
    logic                                    tx_beat_accepted;

    always_comb begin
        boundary_bank           = frame_seen ? ~write_bank : write_bank;
        boundary_bank_available = !bank_ready[boundary_bank] && !((tx_state != TX_IDLE) && (tx_bank == boundary_bank));

        s_axi_tx_tdata          = ram_rd_data;
        s_axi_tx_tkeep          = KEEP_ALL;
        s_axi_tx_tvalid         = (tx_state == TX_SEND);
        s_axi_tx_tlast          = (tx_state == TX_SEND) && (tx_packet_word_index == PACKET_WORDS - 1);
        ram_rd_en               = (tx_state == TX_LOAD);
        ram_rd_addr             = {tx_bank, tx_frame_word_index[BANK_ADDR_WIDTH-1:0]};
        buffer_valid            = (bank_ready != 2'b00) || (tx_state != TX_IDLE);
        tx_busy                 = (tx_state != TX_IDLE);
        tx_beat_accepted        = s_axi_tx_tvalid && s_axi_tx_tready;
    end

    always_ff @(posedge user_clk or negedge reset_n) begin
        if (!reset_n) begin
            tx_state             <= TX_IDLE;
            bank_ready           <= 2'b00;
            write_bank           <= 1'b0;
            tx_bank              <= 1'b0;
            frame_seen           <= 1'b0;
            capture_active       <= 1'b0;
            frame_error_latched  <= 1'b0;
            packet_closed        <= 1'b0;
            rx_frame_word_count  <= '0;
            rx_packet_count      <= '0;
            rx_packet_word_count <= '0;
            tx_frame_word_index  <= '0;
            tx_packet_index      <= '0;
            tx_packet_word_index <= '0;
            ram_wr_en            <= 1'b0;
            ram_wr_addr          <= '0;
            ram_wr_data          <= '0;
            rx_frame_valid       <= 1'b0;
            tx_packet_start      <= 1'b0;
            tx_frame_start       <= 1'b0;
            tx_frame_done        <= 1'b0;
            rx_length_error      <= 1'b0;
            rx_keep_error        <= 1'b0;
            rx_control_error     <= 1'b0;
            rx_overflow          <= 1'b0;
        end else begin
            ram_wr_en        <= 1'b0;
            rx_frame_valid   <= 1'b0;
            tx_packet_start  <= 1'b0;
            tx_frame_start   <= 1'b0;
            tx_frame_done    <= 1'b0;
            rx_length_error  <= 1'b0;
            rx_keep_error    <= 1'b0;
            rx_control_error <= 1'b0;
            rx_overflow      <= 1'b0;

            // RAM reads have one cycle of latency. TX_LOAD issues the read;
            // TX_SEND holds the returned word until Aurora accepts it.
            unique case (tx_state)
                TX_IDLE: begin
                    tx_frame_word_index  <= '0;
                    tx_packet_index      <= '0;
                    tx_packet_word_index <= '0;
                    if (bank_ready[0]) begin
                        tx_bank       <= 1'b0;
                        bank_ready[0] <= 1'b0;
                        tx_state      <= TX_LOAD;
                    end else if (bank_ready[1]) begin
                        tx_bank       <= 1'b1;
                        bank_ready[1] <= 1'b0;
                        tx_state      <= TX_LOAD;
                    end
                end

                TX_LOAD: tx_state <= TX_SEND;

                default: begin  // TX_SEND
                    if (tx_beat_accepted) begin
                        if (tx_frame_word_index == 0) tx_frame_start <= 1'b1;
                        if (tx_packet_word_index == 0) tx_packet_start <= 1'b1;

                        if (tx_frame_word_index == FRAME_WORDS - 1) begin
                            tx_frame_done <= 1'b1;
                            tx_state      <= TX_IDLE;
                        end else begin
                            tx_frame_word_index <= tx_frame_word_index + 1'b1;
                            tx_state            <= TX_LOAD;
                            if (tx_packet_word_index == PACKET_WORDS - 1) begin
                                tx_packet_word_index <= '0;
                                tx_packet_index      <= tx_packet_index + 1'b1;
                            end else begin
                                tx_packet_word_index <= tx_packet_word_index + 1'b1;
                            end
                        end
                    end
                end
            endcase

            // A frame pulse closes the preceding frame and opens a new one.
            // It may coincide with the first valid word of the new frame.
            if (rx_frame_start) begin
                if (frame_seen && capture_active) begin
                    if (!frame_error_latched &&
                        (rx_frame_word_count == FRAME_WORDS) &&
                        (rx_packet_count == PACKETS_PER_FRAME) &&
                        (rx_packet_word_count == PACKET_WORDS) &&
                        packet_closed) begin
                        bank_ready[write_bank] <= 1'b1;
                        rx_frame_valid         <= 1'b1;
                    end else begin
                        rx_length_error <= 1'b1;
                    end
                end

                frame_seen           <= 1'b1;
                write_bank           <= boundary_bank;
                capture_active       <= boundary_bank_available;
                frame_error_latched  <= 1'b0;
                packet_closed        <= 1'b0;
                rx_frame_word_count  <= '0;
                rx_packet_count      <= '0;
                rx_packet_word_count <= '0;

                if (!boundary_bank_available) begin
                    rx_overflow <= 1'b1;
                end else if (m_axi_rx_tvalid) begin
                    ram_wr_en           <= 1'b1;
                    ram_wr_addr         <= {boundary_bank, {BANK_ADDR_WIDTH{1'b0}}};
                    ram_wr_data         <= m_axi_rx_tdata;
                    rx_frame_word_count <= 1;
                    if (m_axi_rx_tkeep != KEEP_ALL) begin
                        rx_keep_error       <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end
                    if (!rx_packet_start) begin
                        rx_control_error    <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end else begin
                        rx_packet_count      <= 1;
                        rx_packet_word_count <= 1;
                        packet_closed        <= m_axi_rx_tlast;
                        if (m_axi_rx_tlast && (PACKET_WORDS != 1)) begin
                            rx_length_error     <= 1'b1;
                            frame_error_latched <= 1'b1;
                        end
                    end
                end else if (rx_packet_start) begin
                    rx_control_error    <= 1'b1;
                    frame_error_latched <= 1'b1;
                end
            end else if (capture_active) begin
                if (rx_packet_start && !m_axi_rx_tvalid) begin
                    rx_control_error    <= 1'b1;
                    frame_error_latched <= 1'b1;
                end

                if (m_axi_rx_tvalid) begin
                    if (rx_frame_word_count < FRAME_WORDS) begin
                        ram_wr_en   <= 1'b1;
                        ram_wr_addr <= {write_bank, rx_frame_word_count[BANK_ADDR_WIDTH-1:0]};
                        ram_wr_data <= m_axi_rx_tdata;
                    end else begin
                        rx_length_error     <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end
                    if (rx_frame_word_count < FRAME_WORDS + 1) rx_frame_word_count <= rx_frame_word_count + 1'b1;

                    if (m_axi_rx_tkeep != KEEP_ALL) begin
                        rx_keep_error       <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end

                    if (rx_packet_start) begin
                        if ((rx_frame_word_count != 0) && ((rx_packet_word_count != PACKET_WORDS) || !packet_closed)) begin
                            rx_length_error     <= 1'b1;
                            frame_error_latched <= 1'b1;
                        end
                        if (rx_packet_count >= PACKETS_PER_FRAME) begin
                            rx_length_error     <= 1'b1;
                            frame_error_latched <= 1'b1;
                        end else begin
                            rx_packet_count <= rx_packet_count + 1'b1;
                        end
                        rx_packet_word_count <= 1;
                        packet_closed        <= m_axi_rx_tlast;
                        if (m_axi_rx_tlast && (PACKET_WORDS != 1)) begin
                            rx_length_error     <= 1'b1;
                            frame_error_latched <= 1'b1;
                        end
                    end else if (rx_packet_count == 0) begin
                        rx_control_error    <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end else if (packet_closed) begin
                        rx_control_error    <= 1'b1;
                        frame_error_latched <= 1'b1;
                    end else begin
                        if (rx_packet_word_count < PACKET_WORDS + 1) rx_packet_word_count <= rx_packet_word_count + 1'b1;
                        if (m_axi_rx_tlast) begin
                            packet_closed <= 1'b1;
                            if (rx_packet_word_count != PACKET_WORDS - 1) begin
                                rx_length_error     <= 1'b1;
                                frame_error_latched <= 1'b1;
                            end
                        end else if (rx_packet_word_count >= PACKET_WORDS - 1) begin
                            rx_length_error     <= 1'b1;
                            frame_error_latched <= 1'b1;
                        end
                    end
                end
            end
        end
    end

endmodule
