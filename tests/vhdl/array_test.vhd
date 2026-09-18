library ieee;
use ieee.std_logic_1164.all;
entity array_test is
    port (clk : in std_logic; rst : in std_logic);
end entity;
architecture rtl of array_test is
    type data_array_t is array (0 to 5) of std_logic_vector(15 downto 0);
    signal a,b,c,d,e,f : data_array_t;
begin
    P1: process(clk)
    begin
        if rising_edge(clk) then
            a <= d;
            b <= e;
            c <= f;
        end if;
    end process;
end architecture;
