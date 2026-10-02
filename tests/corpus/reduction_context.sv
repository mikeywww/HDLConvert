// Synthetic behavioral probe. WIDTH is overridden by the simulation harness.
module reduction_context #(parameter WIDTH=4)
(input [WIDTH-1:0] d, input [2:5] ascending, input scalar,
 output [6:0] direct_result, ascending_result, scalar_result,
 output signed [6:0] signed_result, output [7:0] widened,
 output repeated_parity, sliced_parity,
 output [2:5] split_hi,output signed [3:0] split_lo,
 output split_flag,output[2:0] split_low,output[3:0] sign_hi,sign_lo,
 output inverse_parity,logical_and_result,logical_or_result);
assign direct_result={&d,|d,^d,~&d,~|d,~^d,^~d};
assign ascending_result={&ascending,|ascending,^ascending,~&ascending,~|ascending,~^ascending,^~ascending};
assign scalar_result={&scalar,|scalar,^scalar,~&scalar,~|scalar,~^scalar,^~scalar};
assign signed_result={&$signed(d),|$signed(d),^$signed(d),~&$signed(d),~|$signed(d),~^$signed(d),^~$signed(d)};
assign widened=^d;
assign repeated_parity=^{d,d};
assign sliced_parity=^ascending[2:3];
assign {split_hi,split_lo}=d;
assign {split_flag,split_low}=d;
assign {sign_hi,sign_lo}=$signed(d);
assign inverse_parity=!(^d);
assign logical_and_result=(&d)&&(|ascending);
assign logical_or_result=(|d)||(&ascending);
endmodule
