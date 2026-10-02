// Synthetic coverage probe, not a customer design.
module reductions(input [7:0] d, output a,o,x,na,no,nx);
assign a=&d;
assign o=|d;
assign x=^d;
assign na=~&d;
assign no=~|d;
assign nx=~^d;
endmodule
