library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;
use ieee.std_logic_signed.all;

entity legacy_alu is
    port (
        a, b : in std_logic_vector(7 downto 0);
        opcode : in integer range 0 to 7;
        result : buffer std_logic_vector(7 downto 0);
        negative : out std_logic
    );
end entity;

architecture rtl of legacy_alu is
begin
    negative <= result(7);

    process(a, b, opcode)
        variable value : integer;
    begin
        case opcode is
            when 0 to 3 =>
                value := conv_integer(a) + conv_integer(b);
                result <= conv_std_logic_vector(value, 8);
            when 4 =>
                for i in a'range loop
                    result(i) <= a(i) xor b(i);
                end loop;
            when others =>
                value := conv_integer(a) - conv_integer(b);
                result <= conv_std_logic_vector(value, 8);
        end case;
    end process;
end architecture;
