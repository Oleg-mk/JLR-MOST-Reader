# Gowin EDA batch build of the reader: gw_sh build.tcl  (from reader_gw/board)
set_device GW2AR-LV18QN88C8/I7 -device_version C
add_file ../rtl/rx_runlen.v
add_file ../rtl/rx_classify.v
add_file ../rtl/rx_framer.v
add_file ../rtl/nco_frame.v
add_file ../rtl/ctrl_decode.v
add_file ../rtl/dsp_core.v
add_file ../rtl/spdif_tx.v
add_file ../rtl/amp_out.v
add_file ../rtl/diag_uart_tx.v
add_file ../rtl/diag_fifo.v
add_file ../rtl/diag_cmd.v
add_file ../rtl/diag_cap.v
add_file ../rtl/diag_log.v
add_file ../rtl/reader_core.v
add_file top_tangnano20k.v
add_file tangnano20k.cst
add_file tangnano20k.sdc
set_option -top_module top_tangnano20k
set_option -output_base_name reader
set_option -verilog_std v2001
set_option -use_mspi_as_gpio 1
set_option -use_sspi_as_gpio 1
set_option -timing_driven 1
# placement and routing for timing: with the ring log the chip is 82 % full and the default
# placement left clk_s at 99.7 MHz (0.7 % over 99), these give about 111 MHz (12 %)
set_option -place_option 1
set_option -route_option 1
# the bitstream is read from the flash at 25 MHz (250/10) instead of the default 2.5 MHz: one
# bit a clock, 7.26 Mbit took 2.9 s to configure after the ring woke the FPGA, long enough to
# miss the head unit's Connect; 290 ms now (UG290 Table 3-3). Compression (-bit_compress) is
# accepted by this gw_sh but leaves the bitstream uncompressed (its header says Compress: OFF),
# so it is not set. The bench's COLD measurement (LOGGING.md) proves the figure.
set_option -loading_rate 250/10
run all
