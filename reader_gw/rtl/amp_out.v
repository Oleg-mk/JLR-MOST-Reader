// amp_out.v - what the factory amplifier would play, as S/PDIF, on one clock.
//
// Up to three sources are picked out of the frame (stream 0 is the main one: what the
// amplifier's sink 1 plays; 1 and 2 its other sinks, navigation, phone, chimes), run through
// dsp_core (tone on stream 0 - straight here - then a mix into L and R with gliding gains), and
// leave as S/PDIF (spdif_tx.v) for the TOSLINK transmitter. A sample leaves one frame after the
// frame it came in; the whole delay from the ring is about two frames.
//
// Taken from MOST25-to-AUDIO's amp_out.v with its two clock domains folded into one: the
// commands and the frame bytes came in clk_s, the engine and the outputs ran in clk_r, the
// ring-locked 1024 Fs from the Si514. Here everything is clk_s, and the ring's rate is
// nco_frame's tick train: the engine starts on the tick of phase 0 (run), spdif_tx draws its
// half-cells from the ticks. No injection (the frame is the ring's), no I2S.
//
// Commands (ctrl_decode gives them as host_cmd did; the packet format is theirs):
//
//   01  P  L0 L1 L2  R0 R1 R2      where a stream is in the frame
//     P[1:0]  0 = off (zeros in), 2 = 16 bit, 3 = 24 bit
//     P[2]    mono: the left bytes only, fed to both sides
//     P[5:4]  stream 0..2
//     P[7:6], P[3] zero; anything else is refused whole
//     L0..R2  frame byte index 0..63 of each sample byte, MSB first (L2/R2
//             ignored at 16 bit, R0..R2 when mono)
//   03  A  V3 V2 V1 V0  F  T       one coefficient word
//     A       address 0..63 (the map: sim/dsp_asm.py)
//     V3..V0  the word, Q4.28, most significant byte first
//     F[0]    commit: after this word, the bank written becomes the one in use
//     F[7:1]  zero; anything else is refused whole
//     T       the set's tag: the same in every word of one set, another for the next
//
// Coefficients live in two banks. The writer fills the one not in use, word by word, and
// commits with the last word; the engine switches banks only between two runs of its program,
// so no frame is ever computed from half an old and half a new set. A set is a transaction
// (audit R03): a commit switches banks only if every address 0 .. DSP_C_IMAGE-1 (dsp_map.vh)
// has been written with the commit's tag since the last commit; a word with another tag starts
// the set anew, a commit that finds it incomplete is dropped and starts it anew too.
//
// Neither the banks nor the engine's gains are cleared by a reset: after power up everything is
// zero, so the output is silent until a set has been written; ctrl_decode writes one with the
// start-up levels right after reset.
module amp_out (
    input  wire        clk,
    input  wire        rst,
    // commands (ctrl_decode: host_cmd's ok / cmd / p)
    input  wire        cmd_ok,
    input  wire [7:0]  cmd,
    input  wire [55:0] cmd_p,
    // frame bytes from rx_framer
    input  wire        byte_we,
    input  wire [5:0]  byte_addr,
    input  wire [7:0]  byte_data,
    input  wire        frame_done,
    // the frame train (nco_frame)
    input  wire        run,                 // the train is pinned to the ring and running
    input  wire        tick,
    input  wire        fstart,              // the tick is the frame start's (tick && phase_n == 0)
    input  wire [2:0]  sub,
    input  wire [9:0]  phase_n,
    input  wire        rate48,              // the ring runs at 48 kHz (S/PDIF channel status)
    output wire [7:0]  spdif_word,          // the line, 8 samples a clock, bit 0 first (OSER8)
    output wire        spdif,               // the line's level
    output wire        overrun,             // the engine missed a frame (sticky)
    // the log
    output wire        cq_ok,               // the command bus as registered here
    output wire [7:0]  cq_cmd,
    output wire [55:0] cq_p,
    output wire        commit_ok,           // pulse: a commit switched to its set (tag commit_tag)
    output wire        commit_bad,          // pulse: a commit found its set incomplete
    output wire [7:0]  commit_tag,
    output wire        bank_sw,             // pulse: the engine took the new bank
    output wire        estart,              // pulse: the engine starts on in_w
    output wire [143:0] in_w_o,
    output wire [47:0] out_w_o
);
    integer k, s;

    // ------------------------------------------------ command 01
    // The packet is registered once more here: decoded straight from the
    // sender's registers, across the chip, the 01 and 03 writes were the
    // slowest path. A packet holds for at least a clock, so a clock costs nothing.
    reg        ok_q  /* synthesis syn_preserve = 1 */;
    reg [7:0]  cmd_q /* synthesis syn_preserve = 1 */;
    reg [55:0] p_q   /* synthesis syn_preserve = 1 */;
    always @(posedge clk) begin ok_q <= cmd_ok & ~rst; cmd_q <= cmd; p_q <= cmd_p; end
    assign cq_ok = ok_q; assign cq_cmd = cmd_q; assign cq_p = p_q;
    wire [7:0] p0 = p_q[55:48];
    wire       p0_ok = p0[7:6] == 2'd0 && !p0[3] && p0[5:4] != 2'd3 && p0[1:0] != 2'd1;
    // decoded once more: a strobe per stream and the fields, so the writes
    // below are plain enables (the 6s+k address arithmetic was a slow path)
    reg  [2:0]  w01;                        // write stream 0 / 1 / 2
    reg  [1:0]  w01_w;
    reg         w01_m;
    reg  [35:0] w01_p;
    always @(posedge clk) begin
        for (s = 0; s < 3; s = s + 1) w01[s] <= ok_q && cmd_q == 8'h01 && p0_ok && p0[5:4] == s[1:0] && !rst;
        w01_w <= p0[1:0]; w01_m <= p0[2];
        for (k = 0; k < 6; k = k + 1) w01_p[6 * k +: 6] <= p_q[45 - 8 * k -: 6];
    end
    reg  [5:0] pnew [0:17];                 // stream s: L0 L1 L2 R0 R1 R2 at 6s..6s+5
    reg  [1:0] wnew [0:2];
    reg        mnew [0:2];
    always @(posedge clk) begin
        if (rst) begin
            for (s = 0; s < 3; s = s + 1) begin wnew[s] <= 2'd0; mnew[s] <= 1'b0; end
            for (k = 0; k < 18; k = k + 1) pnew[k] <= 6'd0;
        end else begin
            for (s = 0; s < 3; s = s + 1)
                if (w01[s]) begin
                    wnew[s] <= w01_w;
                    mnew[s] <= w01_m;
                    for (k = 0; k < 6; k = k + 1) pnew[6 * s + k] <= w01_p[6 * k +: 6];
                end
        end
    end

    // --------------------------------------- pick the bytes of each frame
    // A command takes effect at the next frame boundary, so no frame is ever
    // put together from two different sets of positions.
    // The byte stream is registered once more here: 18 address compares fed
    // straight from rx_framer's registers, across the chip, were the
    // slowest path. frame_done is delayed with it, so byte 63 lands before
    // the copy into fin.
    reg       we_q, fd_q;
    reg [5:0] ba_q;
    reg [7:0] bd_q;
    always @(posedge clk) begin
        we_q <= byte_we & ~rst; fd_q <= frame_done & ~rst; ba_q <= byte_addr; bd_q <= byte_data;
    end
    reg [5:0] pos [0:17];                   // in effect for the frame being collected
    reg [7:0] cur [0:17];                   // being collected
    reg [7:0] fin [0:17];                   // last complete frame, stable ~1 frame
    reg [1:0] wid [0:2], wfin [0:2];        // width in effect / with fin
    reg       mon [0:2], mfin [0:2];
    always @(posedge clk) begin
        if (rst) begin
            for (s = 0; s < 3; s = s + 1) begin
                wid[s] <= 2'd0; wfin[s] <= 2'd0; mon[s] <= 1'b0; mfin[s] <= 1'b0;
            end
            for (k = 0; k < 18; k = k + 1) pos[k] <= 6'd0;
        end else begin
            if (we_q)
                for (k = 0; k < 18; k = k + 1)
                    if (ba_q == pos[k]) cur[k] <= bd_q;
            if (fd_q) begin
                for (k = 0; k < 18; k = k + 1) begin
                    fin[k] <= cur[k];
                    pos[k] <= pnew[k];
                end
                for (s = 0; s < 3; s = s + 1) begin
                    wfin[s] <= wid[s]; wid[s] <= wnew[s];
                    mfin[s] <= mon[s]; mon[s] <= mnew[s];
                end
            end
        end
    end

    // the samples, as the engine takes them: fin changes at a frame completion,
    // about 2.6 us (128 ticks) before the train's frame start, where the
    // engine latches in_w, and holds for the rest of the frame
    reg [143:0] in_w;
    reg [23:0]  l24, r24;
    always @(posedge clk) begin
        for (k = 0; k < 3; k = k + 1) begin
            l24 = (wfin[k] == 2'd3) ? {fin[6 * k], fin[6 * k + 1], fin[6 * k + 2]} :
                  (wfin[k] == 2'd2) ? {fin[6 * k], fin[6 * k + 1], 8'd0} : 24'd0;
            r24 = (wfin[k] == 2'd3) ? {fin[6 * k + 3], fin[6 * k + 4], fin[6 * k + 5]} :
                  (wfin[k] == 2'd2) ? {fin[6 * k + 3], fin[6 * k + 4], 8'd0} : 24'd0;
            in_w[143 - 48 * k -: 24] <= l24;
            in_w[119 - 48 * k -: 24] <= mfin[k] ? l24 : r24;
        end
    end

    // ------------------------------------------- command 03, banks
`include "dsp_map.vh"
    reg [31:0] cmem [0:127];                // {bank, address}
    integer i;
    initial for (i = 0; i < 128; i = i + 1) cmem[i] = 32'd0;
    // not reset: a reset must not change what the engine plays
    reg bank_w = 1'b0, c_bank = 1'b0, pend = 1'b0;
    reg bank_r = 1'b1;                      // bank 1 (zeros) until the first commit
    wire w_ok = ok_q && cmd_q == 8'h03 && p_q[55:54] == 2'd0 && p_q[15:9] == 7'd0;
    reg         w03;                        // decoded once more, as for command 01
    reg  [5:0]  w03_a;
    reg  [31:0] w03_v;
    reg         w03_c;
    reg  [7:0]  w03_t;
    always @(posedge clk) begin
        w03 <= w_ok; w03_a <= p_q[53:48]; w03_v <= p_q[47:16]; w03_c <= p_q[8]; w03_t <= p_q[7:0];
    end
    // the set being written: its tag and the addresses it has so far
    reg  [7:0]             t_cur = 8'd0;
    reg  [DSP_C_IMAGE-1:0] have = {DSP_C_IMAGE{1'b0}};
    // The word's tag against t_cur and the word's address as one bit, both
    // taken a clock early from p_q, where w03_t and w03_a come from: same_q is
    // w03_t == t_cur and a_bit the bit of w03_a, in every clock. t_cur is
    // compared as it will be then (w03_t if a word lands now), so words one
    // clock apart compare right. Done in the clock of the word, the compare,
    // the 47-bit pick and the AND over all of it came to 9.3 ns before the
    // commit's enables: inside 10.1 ns, not inside check_timing.py's 10 %.
    reg                    same_q = 1'b0;
    reg  [DSP_C_IMAGE-1:0] a_bit = {DSP_C_IMAGE{1'b0}};
    always @(posedge clk) begin
        same_q <= p_q[7:0] == (w03 ? w03_t : t_cur);
        a_bit  <= {{(DSP_C_IMAGE-1){1'b0}}, 1'b1} << p_q[53:48];
    end
    wire [DSP_C_IMAGE-1:0] have_n = (same_q ? have : {DSP_C_IMAGE{1'b0}}) | a_bit;
    assign commit_ok  = w03 && w03_c && (&have_n);
    assign commit_bad = w03 && w03_c && !(&have_n);
    assign commit_tag = w03_t;
    wire        running;
    always @(posedge clk) begin
        if (w03) begin
            cmem[{bank_w, w03_a}] <= w03_v;
            t_cur <= w03_t;
            if (w03_c) begin
                have <= {DSP_C_IMAGE{1'b0}};
                if (&have_n) begin
                    c_bank <= bank_w; pend <= 1'b1; bank_w <= ~bank_w;
                end
            end else begin
                have <= have_n;
            end
        end
        // the engine takes the new bank between two runs
        if (pend && !running) begin
            bank_r <= c_bank; pend <= 1'b0;
        end
    end

    // ------------------------------------------------ engine
    wire [5:0]  c_addr;
    reg  [31:0] c_q;
    wire [47:0] out_w;
    wire        start = run && fstart;     // run && tick && phase_n == 0, made by nco_frame with the tick
    assign bank_sw = pend && !running;
    assign estart  = start;
    assign in_w_o  = in_w;
    assign out_w_o = out_w;
    always @(posedge clk) c_q <= cmem[{bank_r, c_addr}];
    dsp_core u_dsp (.clk(clk), .rst(rst), .start(start), .in_w(in_w), .c_addr(c_addr),
                    .c_q(c_q), .out_w(out_w), .running(running), .overrun(overrun));

    // ------------------------------------------------ S/PDIF out
    // out_w is written during the program run (~450 clocks after the frame
    // start) and latched by spdif_tx at the next frame start
    spdif_tx u_sp (.clk(clk), .run(run), .tick(tick), .fstart(fstart), .sub(sub), .phase_n(phase_n), .lr(out_w),
                   .rate48(rate48), .word(spdif_word), .out(spdif));
endmodule
