library ieee;
use ieee.std_logic_1164.all;
entity initializer_drivers is
    port(clk, d, en : in std_logic;
         ready, comb, stored : out std_logic);
end entity;
architecture rtl of initializer_drivers is
    signal ready_i : std_logic := '0';
    signal comb_i : std_logic := '1';
    signal stored_i : std_logic := '1';
begin
    ready_i <= '1' when en = '1' and d = '1' else '0';
    process(all)
    begin
        if d = '1' then
            comb_i <= '0';
        else
            comb_i <= '1';
        end if;
    end process;
    process(clk)
        variable v : std_logic := '0';
    begin
        if rising_edge(clk) then
            v := not d;
            stored_i <= v;
        end if;
    end process;
    ready <= ready_i;
    comb <= comb_i;
    stored <= stored_i;
end architecture;
