library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity rtl_demo is
    generic (WIDTH : positive := 16);
    port (clk, rst_n, en : in std_logic;
          din : in std_logic_vector(WIDTH-1 downto 0);
          dout : out std_logic_vector(WIDTH-1 downto 0);
          valid : out std_logic);
end entity;

architecture rtl of rtl_demo is
    type sample_array_t is array (3 to 6) of std_logic_vector(WIDTH-1 downto 0);
    type state_t is (IDLE, RUN);
    signal pipe_data, snapshot : sample_array_t;
    signal state : state_t := IDLE;
    signal count : unsigned(3 downto 0) := (others => '0');
begin
    p_data : process(clk, rst_n)
    begin
        if rst_n = '0' then
            pipe_data <= (others => (others => '0'));
            snapshot <= (others => (others => '0'));
            count <= (others => '0');
            state <= IDLE;
        elsif rising_edge(clk) then
            if en = '1' then
                pipe_data(3) <= din;
                for k in 4 to 6 loop
                    pipe_data(k) <= pipe_data(k-1);
                end loop;
                snapshot <= pipe_data;
                count <= count + 1;
                state <= RUN;
            end if;
        end if;
    end process;
    dout <= snapshot(6);
    process(all)
    begin
        case state is
            when IDLE => valid <= '0';
            when RUN => valid <= en;
        end case;
    end process;
end architecture;
