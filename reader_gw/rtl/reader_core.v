// reader_core.v - the JLR MOST reader, on one clock: the ring's samples in, S/PDIF out, and the
// ring log out over the module's USB-UART.
//
//   samp (8 per clk) -> rx_runlen -> rx_classify -> rx_framer    the frames, bytes and edges
//        rx_framer frame edges -> nco_frame                       the frame train: 1024 ticks a frame
//        rx_framer frame bytes -> ctrl_decode -> commands         the control channel, read here
//        rx_framer frame bytes + commands + train -> amp_out      the streams, the engine, S/PDIF
//        every stage -> diag_log -> uart_tx                       the log (reader_gw/LOGGING.md)
//
// Everything runs on clk, the sampler's 99 MHz word clock (the IDES8 of the Tang Nano 20K
// delivers 8 samples of the receiver's line a clock, 1.26 ns apart). There is no ring-locked
// clock: the ring's rate lives in nco_frame's tick train, and the S/PDIF line leaves as 8
// samples a clock (spdif_word) for an OSER8, its edges on the same 1.26 ns grid.
// Nothing here ever reaches the ring: the FOT transmitter is fed by the board's buffer alone.
//
// Two resets. rst is power-up only: the log and rx_runlen (the line's run counter, whose first
// edge after a dark spell is what ends it) never see anything else. rst_c resets the rest, the
// core: it is power-up or the log's hold (the supply's loss emulated while the laptop is
// attached, LOGGING.md), registered by the board top in its own reset register.
//
// The board top wraps this with the PLL, the IDES8 on the receiver's line, the OSER8 on the
// transmitter's, the UART pins and the LEDs (status).
module reader_core #(
    parameter RELEARN   = 495000,           // clk without a locked frame before the receiver relearns
    parameter PAR_LEARN = 64,               // ctrl_decode: frames of one parity before it is known
    parameter PAR_BAD   = 4,                //              frames of the other before it is forgotten
    parameter D_TICKS   = 128,              // nco_frame: ticks from a frame's UI 0 to the train's frame start
    parameter AVG_LOG2  = 6,                //            the period over 2^AVG_LOG2 frames
    // the log (diag_log.v); simulations shrink the times
    parameter [31:0] BUILD_ID = 32'h0,
    parameter LOG_US_MS     = 1000,
    parameter LOG_STAT_LOG2 = 21,
    parameter LOG_CAP_NBW   = 4,
    parameter LOG_CAP_BW    = 11,
    parameter LOG_CAP_RUN_MS = 10,
    parameter LOG_CAP_FRM_MS = 50,
    parameter LOG_WAKE2_MS  = 2000,
    parameter LOG_UNL_HOLD_MS = 1000,
    parameter LOG_UNL_GAP_MS  = 10000,
    parameter LOG_POS_WAIT_MS = 5000,
    parameter LOG_POS_GAP_MS  = 10000,
    parameter LOG_STOP_US   = 1000,
    parameter LOG_ATTACH_MS = 2000,
    parameter LOG_DARK_DEF_MS = 100
) (
    input  wire        clk,
    input  wire        rst,                 // power-up
    input  wire        rst_c,               // the core: power-up or hold, registered by the top
    input  wire [7:0]  samp,                // the receiver's line, 8 samples a clock, bit 0 the earliest
    output wire [7:0]  spdif_word,          // the S/PDIF line, 8 samples a clock, bit 0 the earliest
    output wire        spdif,               // its level
    output wire [7:0]  status,              // for LEDs and the bench, see below
    output wire        uart_tx,             // the log, 3 Mbaud 8N1
    input  wire        uart_rx,             // the laptop's commands
    output wire        hold                 // the log asks for the core to be held
);
    // the sample time base: wc counts words, a sample is wc x 8 + its index (in the core's reset:
    // nco_frame relies on wc being 0 in the reset's last clock)
    reg [28:0] wc;
    always @(posedge clk) wc <= rst_c ? 29'd0 : wc + 29'd1;

    // ------------------------------------------------------------ receiver
    wire rv, rl, gl; wire [7:0] rlen; wire [31:0] run_tm;
    wire sv, sl; wire [1:0] sym; wire [3:0] slen; wire [15:0] ui_q; wire [31:0] sym_tm;
    wire relearn; wire [7:0] sraw; wire [15:0] bias;
    wire bwe, fd, fpar, bk, rx_lk, er; wire [5:0] ba; wire [7:0] bd; wire [3:0] bi;
    wire fev, fer; wire [31:0] fet, fen;
    wire pre_done; wire [11:0] pre_sig, com_sig;
    rx_runlen   u_rl (.clk(clk), .rst(rst), .samp(samp), .wc(wc), .run_valid(rv), .run_len(rlen),
                      .run_level(rl), .glitch(gl), .run_t(run_tm));
    rx_classify #(.RELEARN(RELEARN))
                u_cl (.clk(clk), .rst(rst_c), .run_valid(rv), .run_len(rlen), .run_level(rl),
                      .glitch(gl), .run_t(run_tm), .locked(rx_lk), .sym_valid(sv), .sym(sym),
                      .sym_len(slen), .sym_level(sl), .ui_q(ui_q), .sym_t(sym_tm),
                      .relearn_o(relearn), .sym_raw(sraw), .b_o(bias));
    rx_framer   u_fr (.clk(clk), .rst(rst_c), .sym_valid_i(sv), .sym_i(sym), .sym_t_i(sym_tm), .ui_q(ui_q),
                      .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                      .frame_par(fpar), .blk_idx(bi), .blk_known(bk), .locked(rx_lk),
                      .err(er), .fs_sq(), .fe_valid(fev), .fe_rise(fer), .fe_t(fet), .fe_next(fen),
                      .pre_done_o(pre_done), .pre_sig_o(pre_sig), .com_sig_o(com_sig));

    // ------------------------------------------------------------ the frame train
    wire run, tick, fstart, per_ok, rate48, pin; wire [2:0] sub; wire [9:0] phase_n; wire [31:0] per, err_last;
    nco_frame #(.D_TICKS(D_TICKS), .AVG_LOG2(AVG_LOG2))
              u_nco (.clk(clk), .rst(rst_c), .wc(wc), .locked(rx_lk), .fe_valid(fev), .fe_rise(fer), .fe_t(fet), .fe_next(fen),
                     .run(run), .tick(tick), .fstart(fstart), .sub(sub), .phase_n(phase_n), .per(per), .per_ok(per_ok),
                     .rate48(rate48), .err_last(err_last), .pin_o(pin));

    // ------------------------------------------------------------ the control channel
    wire cok, tel, hit, dropped, par_known, par_sense, cbusy; wire [7:0] ccmd; wire [55:0] cp; wire [13:0] dstate;
    ctrl_decode #(.PAR_LEARN(PAR_LEARN), .PAR_BAD(PAR_BAD))
                u_ctl (.clk(clk), .rst(rst_c), .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                       .frame_par(fpar), .blk_idx(bi), .blk_known(bk), .locked(rx_lk),
                       .ok(cok), .cmd(ccmd), .p(cp), .tel(tel), .hit(hit), .dropped(dropped),
                       .par_known_o(par_known), .par_sense_o(par_sense), .busy(cbusy), .dstate(dstate));

    // ------------------------------------------------------------ the streams, the engine, S/PDIF
    wire overrun, cq_ok, commit_ok, commit_bad, bank_sw, estart; wire [7:0] cq_cmd, commit_tag; wire [55:0] cq_p;
    wire [143:0] in_w; wire [47:0] out_w;
    amp_out u_amp (.clk(clk), .rst(rst_c), .cmd_ok(cok), .cmd(ccmd), .cmd_p(cp),
                   .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                   .run(run), .tick(tick), .fstart(fstart), .sub(sub), .phase_n(phase_n), .rate48(rate48),
                   .spdif_word(spdif_word), .spdif(spdif), .overrun(overrun),
                   .cq_ok(cq_ok), .cq_cmd(cq_cmd), .cq_p(cq_p), .commit_ok(commit_ok), .commit_bad(commit_bad),
                   .commit_tag(commit_tag), .bank_sw(bank_sw), .estart(estart), .in_w_o(in_w), .out_w_o(out_w));

    // ------------------------------------------------------------ the log
    diag_log #(.BUILD_ID(BUILD_ID), .US_MS(LOG_US_MS), .STAT_LOG2(LOG_STAT_LOG2),
               .CAP_NBW(LOG_CAP_NBW), .CAP_BW(LOG_CAP_BW), .CAP_RUN_MS(LOG_CAP_RUN_MS), .CAP_FRM_MS(LOG_CAP_FRM_MS),
               .WAKE2_MS(LOG_WAKE2_MS), .UNLOCK_HOLD_MS(LOG_UNL_HOLD_MS), .UNLOCK_GAP_MS(LOG_UNL_GAP_MS),
               .POS_WAIT_MS(LOG_POS_WAIT_MS), .POS_GAP_MS(LOG_POS_GAP_MS), .STOP_US(LOG_STOP_US),
               .ATTACH_MS(LOG_ATTACH_MS), .DARK_DEF_MS(LOG_DARK_DEF_MS))
             u_log (.clk(clk), .rst(rst),
                    .rv(rv), .rlen(rlen), .rl(rl), .gl(gl),
                    .sv(sv), .sym(sym), .sl(sl), .sraw(sraw), .ui_q(ui_q), .bias(bias), .relearn(relearn),
                    .bwe(bwe), .ba(ba), .bd(bd), .fd(fd), .fpar(fpar), .bi(bi), .bk(bk), .lk(rx_lk), .er(er),
                    .pre_done(pre_done), .pre_sig(pre_sig), .com_sig(com_sig),
                    .run(run), .per_ok(per_ok), .rate48(rate48), .per(per), .err_last(err_last), .pin(pin),
                    .tel(tel), .hit(hit), .dropped(dropped), .par_known(par_known), .par_sense(par_sense), .dstate(dstate),
                    .c_ok(cq_ok), .c_cmd(cq_cmd), .c_p(cq_p), .commit_ok(commit_ok), .commit_bad(commit_bad),
                    .commit_tag(commit_tag), .bank_sw(bank_sw), .estart(estart), .in_w(in_w), .out_w(out_w),
                    .overrun(overrun), .txd(uart_tx), .rxd(uart_rx), .hold(hold));

    assign status = {overrun, dropped, hit, par_known, per_ok, bk, run, rx_lk};
endmodule
