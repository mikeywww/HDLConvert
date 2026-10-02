// Synthetic probe for concatenated assignment target lowering.
module concat_target(input [7:0] d, output [3:0] hi,lo);
assign {hi,lo}=d;
endmodule
