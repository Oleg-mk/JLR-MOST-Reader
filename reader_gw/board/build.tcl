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
run all
