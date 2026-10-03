// Timing constraints for top_tangnano20k.v, the reader board: one clock domain.
// clk27 : the module's crystal.
// fclk  : 396 MHz from the PLL, FCLK of the IDES8 and the OSER8.
// clk_s : 99 MHz from fclk through CLKDIV /4: PCLK of both and the whole design.
// No other clock: the ring's rate lives in nco_frame's tick train, not in a clock.
// The two board pins need no I/O constraint: both go through the IOLOGIC (IDES8, OSER8), whose
// registers sit in the I/O cell and are clocked by fclk and clk_s; what reaches the core is
// already a clk_s register.
create_clock -name clk27 -period 37.037 [get_ports {clk27}]
create_generated_clock -name fclk -source [get_ports {clk27}] -master_clock clk27 -multiply_by 44 -divide_by 3 [get_pins {u_pll/CLKOUT}]
create_generated_clock -name clk_s -source [get_pins {u_pll/CLKOUT}] -master_clock fclk -divide_by 4 [get_pins {u_div/CLKOUT}]
