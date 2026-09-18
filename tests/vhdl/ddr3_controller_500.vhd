-- DDR3 command-controller fixture for VHDL-to-SystemVerilog conversion.
-- Language: VHDL-2008; single clock domain; abstract external PHY interface.
-- Not a board-ready DDR3 controller: no DQS, training, or physical I/O.
-- Timing generics are illustrative clock counts, not device specifications.
-- PHY accepts one complete BL8 payload; it handles serialization and latency.
-- Requests use valid/ready; responses use valid/ready and remain stable.
-- Address layout: row[27:13], bank[12:10], column[9:0].
-- Column low three bits are cleared for aligned eight-beat bursts.
-- One outstanding request, closed-page policy, periodic refresh.
-- Coverage: records, arrays, enums, functions, generate, slices, numeric_std.
-- The file contains synthesizable RTL only; protocol checks belong in a testbench.
-- Initialization: reset, CKE, precharge, MR2/MR3/MR1/MR0, ZQCL.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity ddr3_controller_500 is
    generic (
        G_RESET_CYCLES : positive := 32;
        G_CKE_CYCLES   : positive := 16;
        G_TRP          : positive := 4;
        G_TRCD         : positive := 4;
        G_TRAS         : positive := 10;
        G_TWR          : positive := 6;
        G_TRTP         : positive := 4;
        G_TRFC         : positive := 24;
        G_TMRD         : positive := 4;
        G_TMOD         : positive := 12;
        G_TZQINIT      : positive := 64;
        G_REFI        : positive := 780;
        G_DEBUG       : boolean := true
    );
    port (
        clk           : in  std_logic;
        rst_n         : in  std_logic;
        req_valid     : in  std_logic;
        req_ready     : out std_logic;
        req_write     : in  std_logic;
        req_addr      : in  std_logic_vector(27 downto 0);
        req_wdata     : in  std_logic_vector(127 downto 0);
        req_wstrb     : in  std_logic_vector(15 downto 0);
        rsp_valid     : out std_logic;
        rsp_ready     : in  std_logic;
        rsp_rdata     : out std_logic_vector(127 downto 0);
        rsp_is_write  : out std_logic;
        init_done     : out std_logic;
        phy_wready    : in  std_logic;
        phy_wdone     : in  std_logic;
        phy_rvalid    : in  std_logic;
        phy_rdata     : in  std_logic_vector(127 downto 0);
        phy_wvalid    : out std_logic;
        phy_wdata     : out std_logic_vector(127 downto 0);
        phy_wmask     : out std_logic_vector(15 downto 0);
        phy_read      : out std_logic;
        ddr_reset_n   : out std_logic;
        ddr_cke       : out std_logic;
        ddr_cs_n      : out std_logic;
        ddr_ras_n     : out std_logic;
        ddr_cas_n     : out std_logic;
        ddr_we_n      : out std_logic;
        ddr_ba        : out std_logic_vector(2 downto 0);
        ddr_addr      : out std_logic_vector(14 downto 0);
        debug_state   : out std_logic_vector(5 downto 0);
        debug_count   : out std_logic_vector(31 downto 0);
        debug_parity  : out std_logic_vector(15 downto 0)
    );
end entity ddr3_controller_500;

architecture rtl of ddr3_controller_500 is
    subtype row_t is std_logic_vector(14 downto 0);
    subtype bank_t is natural range 0 to 7;
    subtype timer_t is natural range 0 to 65535;
    type state_t is (
        S_RESET, S_CKE_LOW, S_CKE_WAIT, S_INIT_PRE,
        S_MR2, S_MR3, S_MR1, S_MR0, S_ZQ,
        S_INIT_DONE, S_IDLE, S_ACT, S_COLUMN,
        S_WRITE_DONE, S_READ_DATA, S_RECOVERY,
        S_PRE, S_RESPONSE, S_REFRESH, S_WAIT
    );
    type row_array_t is array (0 to 7) of row_t;
    type count_array_t is array (0 to 7) of unsigned(15 downto 0);
    type request_t is record
        write_en : std_logic;
        row      : row_t;
        bank     : std_logic_vector(2 downto 0);
        col      : std_logic_vector(9 downto 0);
        data     : std_logic_vector(127 downto 0);
        strobe   : std_logic_vector(15 downto 0);
    end record;
    constant C_NOP   : std_logic_vector(2 downto 0) := "111";
    constant C_ACT   : std_logic_vector(2 downto 0) := "011";
    constant C_READ  : std_logic_vector(2 downto 0) := "101";
    constant C_WRITE : std_logic_vector(2 downto 0) := "100";
    constant C_PRE   : std_logic_vector(2 downto 0) := "010";
    constant C_REF   : std_logic_vector(2 downto 0) := "001";
    constant C_MRS   : std_logic_vector(2 downto 0) := "000";
    constant C_ZQ    : std_logic_vector(2 downto 0) := "110";
    constant C_MR0   : row_t := "000000100100000";
    constant C_MR1   : row_t := "000000000000110";
    constant C_MR2   : row_t := "000000000000000";
    constant C_MR3   : row_t := "000000000000000";
    signal state : state_t := S_RESET;
    signal resume_state : state_t := S_IDLE;
    signal timer : timer_t := 0;
    signal refresh_timer : natural range 0 to G_REFI := 0;
    signal active_age : timer_t := 0;
    signal recovery_timer : timer_t := 0;
    signal request_q : request_t;
    signal rows : row_array_t;
    signal bank_hits : count_array_t;
    signal bank_open : std_logic_vector(7 downto 0) := (others => '0');
    signal command : std_logic_vector(2 downto 0);
    signal address_i : row_t;
    signal bank_i : std_logic_vector(2 downto 0);
    signal ready_i, initialized : std_logic := '0';
    signal response_valid : std_logic := '0';
    signal response_data : std_logic_vector(127 downto 0) := (others => '0');
    signal write_valid_i, read_i : std_logic;
    signal completed : unsigned(31 downto 0) := (others => '0');
    signal parity_i : std_logic_vector(15 downto 0);
    signal selected_hits : unsigned(15 downto 0);
    signal cycle_count : unsigned(31 downto 0) := (others => '0');
    signal busy_count : unsigned(31 downto 0) := (others => '0');
    signal read_count : unsigned(31 downto 0) := (others => '0');
    signal write_count : unsigned(31 downto 0) := (others => '0');
    signal refresh_count : unsigned(31 downto 0) := (others => '0');
    signal request_stalls : unsigned(31 downto 0) := (others => '0');
    signal response_stalls : unsigned(31 downto 0) := (others => '0');
    signal command_count : count_array_t := (others => (others => '0'));
    signal state_seen : std_logic_vector(19 downto 0) := (others => '0');
    signal address_mix : unsigned(31 downto 0) := (others => '0');
    signal activity_lfsr : unsigned(15 downto 0) := x"0001";
    signal last_command : std_logic_vector(2 downto 0) := C_NOP;

    function byte_parity(v : std_logic_vector(7 downto 0)) return std_logic is
        variable p : std_logic := '0';
    begin
        for i in 7 downto 0 loop
            p := p xor v(i);
        end loop;
        return p;
    end function;
begin
    -- Interface wiring and concurrent conditional assignments.
    req_ready <= ready_i;
    rsp_valid <= response_valid;
    rsp_rdata <= response_data;
    rsp_is_write <= request_q.write_en;
    init_done <= initialized;
    phy_wvalid <= write_valid_i;
    phy_wdata <= request_q.data;
    phy_wmask <= not request_q.strobe;
    phy_read <= read_i;
    ddr_cs_n <= '0';
    ddr_ras_n <= command(2);
    ddr_cas_n <= command(1);
    ddr_we_n <= command(0);
    ddr_ba <= bank_i;
    ddr_addr <= address_i;
    ddr_reset_n <= '0' when state = S_RESET else '1';
    ddr_cke <= '0' when state = S_RESET or state = S_CKE_LOW else '1';
    ready_i <= '1' when state = S_IDLE and refresh_timer < G_REFI and response_valid = '0' else '0';
    selected_hits <= bank_hits(to_integer(unsigned(request_q.bank)));

    -- Selected assignment exercises multiple choices and an others choice.
    with state select debug_state <=
        "000000" when S_RESET,
        "000001" when S_CKE_LOW | S_CKE_WAIT,
        "000010" when S_INIT_PRE | S_MR2 | S_MR3 | S_MR1 | S_MR0,
        "000011" when S_ZQ | S_INIT_DONE,
        "000100" when S_IDLE,
        "000101" when S_ACT,
        "000110" when S_COLUMN,
        "000111" when S_WRITE_DONE | S_READ_DATA,
        "001000" when S_RECOVERY | S_PRE,
        "001001" when S_RESPONSE,
        "001010" when S_REFRESH,
        "111111" when others;

    gen_parity : for lane in 0 to 15 generate
        parity_i(lane) <= byte_parity(request_q.data(lane * 8 + 7 downto lane * 8));
    end generate gen_parity;
    gen_debug : if G_DEBUG generate
        debug_count <= std_logic_vector(completed);
        debug_parity <= parity_i;
    end generate gen_debug;
    gen_no_debug : if not G_DEBUG generate
        debug_count <= (others => '0');
        debug_parity <= (others => '0');
    end generate gen_no_debug;

    -- Commands are sampled on the rising clock edge by the abstract PHY.
    decode : process(all)
    begin
        command <= C_NOP;
        address_i <= (others => '0');
        bank_i <= request_q.bank;
        write_valid_i <= '0';
        read_i <= '0';
        case state is
            when S_INIT_PRE =>
                command <= C_PRE;
                address_i(10) <= '1';
            when S_MR2 =>
                command <= C_MRS;
                bank_i <= "010";
                address_i <= C_MR2;
            when S_MR3 =>
                command <= C_MRS;
                bank_i <= "011";
                address_i <= C_MR3;
            when S_MR1 =>
                command <= C_MRS;
                bank_i <= "001";
                address_i <= C_MR1;
            when S_MR0 =>
                command <= C_MRS;
                bank_i <= "000";
                address_i <= C_MR0;
            when S_ZQ =>
                command <= C_ZQ;
                address_i(10) <= '1';
            when S_ACT =>
                command <= C_ACT;
                address_i <= request_q.row;
            when S_COLUMN =>
                address_i(9 downto 0) <= request_q.col;
                address_i(10) <= '0';
                address_i(12) <= '1';
                if request_q.write_en = '1' then
                    write_valid_i <= '1';
                    if phy_wready = '1' then
                        command <= C_WRITE;
                    end if;
                else
                    command <= C_READ;
                    read_i <= '1';
                end if;
            when S_PRE =>
                command <= C_PRE;
                address_i(10) <= '0';
            when S_REFRESH =>
                command <= C_REF;
            when others =>
                null;
        end case;
    end process decode;

    -- Countdown waits deliberately include an extra margin cycle.
    sequencer : process(clk, rst_n)
        variable bank_number : bank_t;
        variable aligned_column : unsigned(9 downto 0);
        variable next_count : unsigned(32 downto 0);
    begin
        if rst_n = '0' then
            state <= S_RESET;
            resume_state <= S_IDLE;
            timer <= G_RESET_CYCLES - 1;
            refresh_timer <= 0;
            active_age <= 0;
            recovery_timer <= 0;
            initialized <= '0';
            response_valid <= '0';
            response_data <= (others => '0');
            completed <= (others => '0');
            bank_open <= (others => '0');
            request_q.write_en <= '0';
            request_q.row <= (others => '0');
            request_q.bank <= (others => '0');
            request_q.col <= (others => '0');
            request_q.data <= (others => '0');
            request_q.strobe <= (others => '0');
            for b in 0 to 7 loop
                rows(b) <= (others => '0');
                bank_hits(b) <= (others => '0');
            end loop;
        elsif rising_edge(clk) then
            bank_number := to_integer(unsigned(request_q.bank));
            if initialized = '1' and refresh_timer < G_REFI then
                refresh_timer <= refresh_timer + 1;
            end if;
            if active_age < 65535 then
                active_age <= active_age + 1;
            end if;
            if recovery_timer > 0 then
                recovery_timer <= recovery_timer - 1;
            end if;
            if response_valid = '1' and rsp_ready = '1' then
                response_valid <= '0';
            end if;
            case state is
                when S_RESET =>
                    if timer = 0 then
                        timer <= G_CKE_CYCLES - 1;
                        state <= S_CKE_LOW;
                    else
                        timer <= timer - 1;
                    end if;
                when S_CKE_LOW =>
                    if timer = 0 then
                        timer <= G_CKE_CYCLES - 1;
                        state <= S_CKE_WAIT;
                    else
                        timer <= timer - 1;
                    end if;
                when S_CKE_WAIT =>
                    if timer = 0 then
                        state <= S_INIT_PRE;
                    else
                        timer <= timer - 1;
                    end if;
                when S_INIT_PRE =>
                    bank_open <= (others => '0');
                    timer <= G_TRP - 1;
                    resume_state <= S_MR2;
                    state <= S_WAIT;
                when S_MR2 =>
                    timer <= G_TMRD - 1;
                    resume_state <= S_MR3;
                    state <= S_WAIT;
                when S_MR3 =>
                    timer <= G_TMRD - 1;
                    resume_state <= S_MR1;
                    state <= S_WAIT;
                when S_MR1 =>
                    timer <= G_TMRD - 1;
                    resume_state <= S_MR0;
                    state <= S_WAIT;
                when S_MR0 =>
                    timer <= G_TMOD - 1;
                    resume_state <= S_ZQ;
                    state <= S_WAIT;
                when S_ZQ =>
                    timer <= G_TZQINIT - 1;
                    resume_state <= S_INIT_DONE;
                    state <= S_WAIT;
                when S_INIT_DONE =>
                    initialized <= '1';
                    refresh_timer <= 0;
                    state <= S_IDLE;
                when S_IDLE =>
                    if refresh_timer = G_REFI then
                        state <= S_REFRESH;
                    elsif req_valid = '1' and ready_i = '1' then
                        request_q.write_en <= req_write;
                        request_q.row <= req_addr(27 downto 13);
                        request_q.bank <= req_addr(12 downto 10);
                        aligned_column := unsigned(req_addr(9 downto 0));
                        aligned_column(2 downto 0) := "000";
                        request_q.col <= std_logic_vector(aligned_column);
                        request_q.data <= req_wdata;
                        request_q.strobe <= req_wstrb;
                        state <= S_ACT;
                    end if;
                when S_ACT =>
                    rows(bank_number) <= request_q.row;
                    bank_open(bank_number) <= '1';
                    bank_hits(bank_number) <= bank_hits(bank_number) + 1;
                    active_age <= 0;
                    timer <= G_TRCD - 1;
                    resume_state <= S_COLUMN;
                    state <= S_WAIT;
                when S_COLUMN =>
                    if request_q.write_en = '1' then
                        if phy_wready = '1' then
                            state <= S_WRITE_DONE;
                        end if;
                    else
                        recovery_timer <= G_TRTP;
                        state <= S_READ_DATA;
                    end if;
                when S_WRITE_DONE =>
                    if phy_wdone = '1' then
                        recovery_timer <= G_TWR;
                        response_data <= (others => '0');
                        state <= S_RECOVERY;
                    end if;
                when S_READ_DATA =>
                    if phy_rvalid = '1' then
                        response_data <= phy_rdata;
                        state <= S_RECOVERY;
                    end if;
                when S_RECOVERY =>
                    if active_age >= G_TRAS and recovery_timer = 0 then
                        state <= S_PRE;
                    end if;
                when S_PRE =>
                    bank_open(bank_number) <= '0';
                    timer <= G_TRP - 1;
                    resume_state <= S_RESPONSE;
                    state <= S_WAIT;
                when S_RESPONSE =>
                    response_valid <= '1';
                    next_count := resize(completed, 33) + to_unsigned(1, 33);
                    completed <= next_count(31 downto 0);
                    state <= S_IDLE;
                when S_REFRESH =>
                    refresh_timer <= 0;
                    timer <= G_TRFC - 1;
                    resume_state <= S_IDLE;
                    state <= S_WAIT;
                when S_WAIT =>
                    if timer = 0 then
                        state <= resume_state;
                    else
                        timer <= timer - 1;
                    end if;
            end case;
        end if;
    end process sequencer;

    -- Synthesizable activity counters broaden the conversion test corpus.
    statistics : process(clk, rst_n)
        variable feedback : std_logic;
        variable command_index : natural range 0 to 7;
    begin
        if rst_n = '0' then
            cycle_count <= (others => '0');
            busy_count <= (others => '0');
            read_count <= (others => '0');
            write_count <= (others => '0');
            refresh_count <= (others => '0');
            request_stalls <= (others => '0');
            response_stalls <= (others => '0');
            command_count <= (others => (others => '0'));
            state_seen <= (others => '0');
            address_mix <= (others => '0');
            activity_lfsr <= x"0001";
            last_command <= C_NOP;
        elsif rising_edge(clk) then
            cycle_count <= cycle_count + 1;
            last_command <= command;
            feedback := activity_lfsr(15) xor activity_lfsr(13)
                        xor activity_lfsr(12) xor activity_lfsr(10);
            activity_lfsr <= activity_lfsr(14 downto 0) & feedback;
            command_index := to_integer(unsigned(command));
            if command /= C_NOP then
                command_count(command_index) <= command_count(command_index) + 1;
            end if;
            if state /= S_IDLE and state /= S_RESET then
                busy_count <= busy_count + 1;
            end if;
            if req_valid = '1' and ready_i = '0' then
                request_stalls <= request_stalls + 1;
            end if;
            if response_valid = '1' and rsp_ready = '0' then
                response_stalls <= response_stalls + 1;
            end if;
            if state = S_COLUMN and request_q.write_en = '0' then
                read_count <= read_count + 1;
            elsif state = S_COLUMN and request_q.write_en = '1'
                  and phy_wready = '1' then
                write_count <= write_count + 1;
            end if;
            if state = S_REFRESH then
                refresh_count <= refresh_count + 1;
            end if;
            if req_valid = '1' and ready_i = '1' then
                address_mix(27 downto 0) <= address_mix(27 downto 0)
                                           xor unsigned(req_addr);
                address_mix(31 downto 28) <= address_mix(31 downto 28) + 1;
            end if;
            case state is
                when S_RESET =>
                    state_seen(0) <= '1';
                when S_CKE_LOW =>
                    state_seen(1) <= '1';
                when S_CKE_WAIT =>
                    state_seen(2) <= '1';
                when S_INIT_PRE =>
                    state_seen(3) <= '1';
                when S_MR2 =>
                    state_seen(4) <= '1';
                when S_MR3 =>
                    state_seen(5) <= '1';
                when S_MR1 =>
                    state_seen(6) <= '1';
                when S_MR0 =>
                    state_seen(7) <= '1';
                when S_ZQ =>
                    state_seen(8) <= '1';
                when S_INIT_DONE =>
                    state_seen(9) <= '1';
                when S_IDLE =>
                    state_seen(10) <= '1';
                when S_ACT =>
                    state_seen(11) <= '1';
                when S_COLUMN =>
                    state_seen(12) <= '1';
                when S_WRITE_DONE =>
                    state_seen(13) <= '1';
                when S_READ_DATA =>
                    state_seen(14) <= '1';
                when S_RECOVERY =>
                    state_seen(15) <= '1';
                when S_PRE =>
                    state_seen(16) <= '1';
                when S_RESPONSE =>
                    state_seen(17) <= '1';
                when S_REFRESH =>
                    state_seen(18) <= '1';
                when S_WAIT =>
                    state_seen(19) <= '1';
            end case;
        end if;
    end process statistics;
end architecture rtl;
