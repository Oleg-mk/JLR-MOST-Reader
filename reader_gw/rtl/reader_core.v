// reader_core.v - the JLR MOST reader, on one clock: the ring's samples in, S/PDIF out.
//
//   samp (8 per clk) -> rx_runlen -> rx_classify -> rx_framer    the frames, bytes and edges
//        rx_framer frame edges -> nco_frame                       the frame train: 1024 ticks a frame
//        rx_framer frame bytes -> ctrl_decode -> commands         the control channel, read here
//        rx_framer frame bytes + commands + train -> amp_out      the streams, the engine, S/PDIF
//
// Everything runs on clk, the sampler's 99 MHz word clock (the IDES8 of the Tang Nano 20K
// delivers 8 samples of the receiver's line a clock, 1.26 ns apart). There is no ring-locked
// clock: the ring's rate lives in nco_frame's tick train, and the S/PDIF line leaves as 8
// samples a clock (spdif_word) for an OSER8, its edges on the same 1.26 ns grid.
// Nothing here ever reaches the ring: the FOT transmitter is fed by the board's buffer alone.
//
// The board top wraps this with the PLL, the IDES8 on the receiver's line, the OSER8 on the
// transmitter's, and the LEDs (status).
module reader_core #(
    parameter RELEARN   = 495000,           // clk without a locked frame before the receiver relearns
    parameter PAR_LEARN = 64,               // ctrl_decode: frames of one parity before it is known
    parameter PAR_BAD   = 4,                //              frames of the other before it is forgotten
    parameter D_TICKS   = 128,              // nco_frame: ticks from a frame's UI 0 to the train's frame start
    parameter AVG_LOG2  = 6                 //            the period over 2^AVG_LOG2 frames
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  samp,                // the receiver's line, 8 samples a clock, bit 0 the earliest
    output wire [7:0]  spdif_word,          // the S/PDIF line, 8 samples a clock, bit 0 the earliest
    output wire        spdif,               // its level
    output wire [7:0]  status               // for LEDs and the bench, see below
);
    // the sample time base: wc counts words, a sample is wc x 8 + its index
    reg [28:0] wc;
    always @(posedge clk) wc <= rst ? 29'd0 : wc + 29'd1;

    // ------------------------------------------------------------ receiver
    wire rv, rl, gl; wire [7:0] rlen; wire [31:0] run_tm;
    wire sv, sl; wire [1:0] sym; wire [3:0] slen; wire [15:0] ui_q; wire [31:0] sym_tm;
    wire bwe, fd, fpar, bk, rx_lk, er; wire [5:0] ba; wire [7:0] bd; wire [3:0] bi;
    wire fev, fer; wire [31:0] fet;
    rx_runlen   u_rl (.clk(clk), .rst(rst), .samp(samp), .wc(wc), .run_valid(rv), .run_len(rlen),
                      .run_level(rl), .glitch(gl), .run_t(run_tm));
    rx_classify #(.RELEARN(RELEARN))
                u_cl (.clk(clk), .rst(rst), .run_valid(rv), .run_len(rlen), .run_level(rl),
                      .glitch(gl), .run_t(run_tm), .locked(rx_lk), .sym_valid(sv), .sym(sym),
                      .sym_len(slen), .sym_level(sl), .ui_q(ui_q), .sym_t(sym_tm));
    rx_framer   u_fr (.clk(clk), .rst(rst), .sym_valid_i(sv), .sym_i(sym), .sym_t_i(sym_tm), .ui_q(ui_q),
                      .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                      .frame_par(fpar), .blk_idx(bi), .blk_known(bk), .locked(rx_lk),
                      .err(er), .fs_sq(), .fe_valid(fev), .fe_rise(fer), .fe_t(fet));

    // ------------------------------------------------------------ the frame train
    wire run, tick, per_ok, rate48; wire [2:0] sub; wire [9:0] phase_n; wire [31:0] per, err_last;
    nco_frame #(.D_TICKS(D_TICKS), .AVG_LOG2(AVG_LOG2))
              u_nco (.clk(clk), .rst(rst), .wc(wc), .locked(rx_lk), .fe_valid(fev), .fe_rise(fer), .fe_t(fet),
                     .run(run), .tick(tick), .sub(sub), .phase_n(phase_n), .per(per), .per_ok(per_ok),
                     .rate48(rate48), .err_last(err_last));

    // ------------------------------------------------------------ the control channel
    wire cok, tel, hit, dropped, par_known, cbusy; wire [7:0] ccmd; wire [55:0] cp;
    ctrl_decode #(.PAR_LEARN(PAR_LEARN), .PAR_BAD(PAR_BAD))
                u_ctl (.clk(clk), .rst(rst), .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                       .frame_par(fpar), .blk_idx(bi), .blk_known(bk), .locked(rx_lk),
                       .ok(cok), .cmd(ccmd), .p(cp), .tel(tel), .hit(hit), .dropped(dropped),
                       .par_known_o(par_known), .busy(cbusy));

    // ------------------------------------------------------------ the streams, the engine, S/PDIF
    wire overrun;
    amp_out u_amp (.clk(clk), .rst(rst), .cmd_ok(cok), .cmd(ccmd), .cmd_p(cp),
                   .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                   .run(run), .tick(tick), .sub(sub), .phase_n(phase_n), .rate48(rate48),
                   .spdif_word(spdif_word), .spdif(spdif), .overrun(overrun));

    assign status = {overrun, dropped, hit, par_known, per_ok, bk, run, rx_lk};
endmodule
