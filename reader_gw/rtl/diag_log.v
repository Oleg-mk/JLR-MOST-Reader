// diag_log.v - the ring log (reader_gw/LOGGING.md): what the reader sees and decides, as records
// over the module's USB-UART bridge, 3 Mbaud.
//
// Taps from every stage of reader_core come in, each through one register here (nothing is
// computed in front of it). Each record type has a producer that keeps what its record needs
// in registers (a snapshot only where the source would move on) and serves the record a byte at
// a time: ob_k is byte wi of its record, registered, wi being the writer's index. One writer
// takes the highest ready producer whose record fits, steps wi through it and copies the bytes
// into the output FIFO, putting in the sequence number and the XOR; it leaves idle clocks after
// each record. The UART drains the FIFO, bytes back to back. (A first version built each record
// in a shift register of its own: 2300 flip-flops more, and the load enables across the chip were
// the slowest paths.) Serving takes two clocks: the record's 8-byte lane by wi, then the byte in
// it by wi a clock later; a 93-way pick in one clock was 4 ns over.
//
//   producer  record   when
//   0 BLOCK    56 B    frame 15 done (+BLK_DELAY clocks, for the decoder's verdict), or the
//                      next block's first byte 0 if frame 15 never came (partial)
//   1 STATUS   94 B    every 2^STAT_LOG2 clocks
//   2 SET      22 B    a coefficient set's last word (address 46)
//   3 CMD      16 B    a command 01 (a 4-deep queue)
//   4 EVENT    14 B    a slot of the event table that may go (one record a slot a ms)
//   5 CAPTURE  42 B    a dump packet staged by diag_cap
//   6 FILL     42 B    the soak test, while the laptop asks for it
//
// The core held (hold): only while the laptop is attached (keepalive within ATTACH_MS), no edge
// for DARK ms holds the core in reset as the supply would, and after the first edge COLD ms
// more, as a cold start would. Without the laptop hold never rises.
module diag_log #(
    parameter [31:0] BUILD_ID = 32'h0,
    parameter DIV            = 33,          // UART: clk a bit (99 MHz / 3 Mbaud)
    parameter STOP           = 33,          //       clk of the stop bit
    parameter US_DIV         = 99,          // clk a microsecond
    parameter US_MS          = 1000,        // microseconds a millisecond (simulations shrink it)
    parameter STAT_LOG2      = 21,          // STATUS every 2^STAT_LOG2 clk (21.2 ms)
    parameter FIFO_AW        = 12,          // output FIFO: 2^FIFO_AW bytes
    parameter CAP_NBW        = 4,           // capture: 2^CAP_NBW blocks (16 BSRAM)
    parameter CAP_BW         = 11,          //          of 2^CAP_BW entries
    parameter CAP_RUN_MS     = 10,
    parameter CAP_FRM_MS     = 50,
    parameter WAKE2_MS       = 2000,        // the steady-line capture after a wake
    parameter UNLOCK_HOLD_MS = 1000,        // lock held this long before an unlock triggers
    parameter UNLOCK_GAP_MS  = 10000,       // ...and at most one unlock trigger in this long
    parameter POS_WAIT_MS    = 5000,        // a new position waits this long for its audio
    parameter POS_GAP_MS     = 10000,       // ...and at most one position trigger in this long
    parameter STOP_US        = 1000,        // no edge this long: "edges stopped"
    parameter ATTACH_MS      = 2000,        // the laptop is gone this long after its last keepalive
    parameter DARK_DEF_MS    = 100,         // the wake trigger's dark time without the laptop
    parameter CMD_TOUT       = 99000,       // command bytes further apart than this end a packet
    parameter BLK_DELAY      = 12           // clocks from frame 15 done to the BLOCK record
) (
    input  wire         clk,
    input  wire         rst,                // power-up only, never the core's held reset
    // rx_runlen
    input  wire         rv,
    input  wire [7:0]   rlen,
    input  wire         rl,
    input  wire         gl,
    // rx_classify
    input  wire         sv,
    input  wire [1:0]   sym,
    input  wire         sl,
    input  wire [7:0]   sraw,
    input  wire [15:0]  ui_q,
    input  wire [15:0]  bias,
    input  wire         relearn,
    // rx_framer
    input  wire         bwe,
    input  wire [5:0]   ba,
    input  wire [7:0]   bd,
    input  wire         fd,
    input  wire         fpar,
    input  wire [3:0]   bi,
    input  wire         bk,
    input  wire         lk,
    input  wire         er,
    input  wire         pre_done,
    input  wire [11:0]  pre_sig,
    input  wire [11:0]  com_sig,
    // nco_frame
    input  wire         run,
    input  wire         per_ok,
    input  wire         rate48,
    input  wire [31:0]  per,
    input  wire [31:0]  err_last,
    input  wire         pin,
    // ctrl_decode
    input  wire         tel,
    input  wire         hit,
    input  wire         dropped,
    input  wire         par_known,
    input  wire         par_sense,
    input  wire [13:0]  dstate,
    // amp_out: the command bus as it registered it, and what it did
    input  wire         c_ok,
    input  wire [7:0]   c_cmd,
    input  wire [55:0]  c_p,
    input  wire         commit_ok,
    input  wire         commit_bad,
    input  wire [7:0]   commit_tag,
    input  wire         bank_sw,
    input  wire         estart,
    input  wire [143:0] in_w,
    input  wire [47:0]  out_w,
    input  wire         overrun,
    // the UART
    output wire         txd,
    input  wire         rxd,
    // the core held: power off and cold start, emulated while the laptop is attached
    output reg          hold
);
    // shared between the blocks below (declared ahead)
    localparam NP = 7;
    localparam [7:0] L0 = 8'd56, L1 = 8'd94, L2 = 8'd22, L3 = 8'd16, L4 = 8'd14, L5 = 8'd42, L6 = 8'd42;
    reg  [NP-1:0] done;                     // pulse: producer k's record has been taken whole
    reg  [7:0]    wi /* synthesis syn_maxfan = 16 */;   // the byte the producers serve
    reg  [7:0]    wi_d /* synthesis syn_maxfan = 16 */; // wi a clock later: the byte within the lane
    // wi again, for STATUS's 12-lane pick alone (wi -> ln1 was the slowest path in builds where wi's
    // fanout to the seven producers pulled it away; 2026-10-04): kept apart, it sits by that pick
    reg  [7:0]    wi1 /* synthesis syn_preserve = 1 */;
    reg           st_load;                  // pulse: a STATUS was taken (the tb's alignment)
    reg           lost0, lost1, lost2, lost3; // pulses: a record had to be dropped
    wire [NP-1:0] req;
    reg  [7:0]    ob0, ob1, ob2, ob3, ob4, ob5, ob6;
    integer i0, i1, i2, i3, i4, i5, i6, i7, i9;

    // ================================================================ taps, one register each
    // (kept: the same copies amp_out makes of the byte bus were merged with these by synthesis,
    // and the shared register then fed both ends of the chip)
    reg         rv_t, rl_t, gl_t, sv_t, sl_t, rel_t, fpar_t, bk_t, lk_t, er_t, pre_t;
    reg         run_t, perok_t, r48_t, pin_t, tel_t, hit_t, drop_t, pk_t, ps_t, cmok_t, cmbad_t;
    reg         cok_t /* synthesis syn_preserve = 1 */;
    reg [7:0]   cmd_t /* synthesis syn_preserve = 1 */;
    reg         bsw_t, es_t, ovr_t;
    reg         bwe_t /* synthesis syn_preserve = 1 */;
    reg         fd_t  /* synthesis syn_preserve = 1 */;
    reg [5:0]   ba_t  /* synthesis syn_preserve = 1 */;
    reg         ba0_t;                      // ba == 0, taken with ba_t: the BLOCK record's byte-0 test
    reg [7:0]   bd_t  /* synthesis syn_preserve = 1 */;
    reg [3:0]   bi_t  /* synthesis syn_preserve = 1 */;
    reg [7:0]   rlen_t, sraw_t, ctag_t;
    reg [1:0]   sym_t;
    reg [15:0]  ui_t, b_t;
    reg [11:0]  psig_t, csig_t;
    reg [31:0]  per_t, err_t;
    reg [13:0]  ds_t;
    reg [55:0]  cp_t /* synthesis syn_preserve = 1 */;
    always @(posedge clk) begin
        rv_t <= rv & ~rst; rlen_t <= rlen; rl_t <= rl; gl_t <= gl;
        sv_t <= sv & ~rst; sym_t <= sym; sl_t <= sl; sraw_t <= sraw; ui_t <= ui_q; b_t <= bias; rel_t <= relearn;
        bwe_t <= bwe & ~rst; ba_t <= ba; ba0_t <= ba == 6'd0; bd_t <= bd; fd_t <= fd & ~rst; fpar_t <= fpar; bi_t <= bi;
        bk_t <= bk; lk_t <= lk; er_t <= er; pre_t <= pre_done; psig_t <= pre_sig; csig_t <= com_sig;
        run_t <= run; perok_t <= per_ok; r48_t <= rate48; per_t <= per; err_t <= err_last; pin_t <= pin;
        tel_t <= tel; hit_t <= hit; drop_t <= dropped; pk_t <= par_known; ps_t <= par_sense; ds_t <= dstate;
        cok_t <= c_ok & ~rst; cmd_t <= c_cmd; cp_t <= c_p;
        cmok_t <= commit_ok; cmbad_t <= commit_bad; ctag_t <= commit_tag; bsw_t <= bank_sw;
        es_t <= estart; ovr_t <= overrun;
    end

    // ================================================================ time
    reg  [6:0]  usc;
    reg         us;                         // pulse: a microsecond
    reg  [31:0] now;                        // microseconds since power-up
    reg  [9:0]  msc;
    reg         ms;                         // pulse: a millisecond
    reg  [STAT_LOG2-1:0] stc;
    reg         st_tick;
    always @(posedge clk) begin
        if (rst) begin
            usc <= 7'd0; us <= 1'b0; now <= 32'd0; msc <= 10'd0; ms <= 1'b0; stc <= 0; st_tick <= 1'b0;
        end else begin
            us  <= (usc == US_DIV - 1);
            usc <= (usc == US_DIV - 1) ? 7'd0 : usc + 7'd1;
            if (us) now <= now + 32'd1;
            ms  <= us && (msc == US_MS - 1);
            if (us) msc <= (msc == US_MS - 1) ? 10'd0 : msc + 10'd1;
            stc <= stc + 1'b1;
            st_tick <= &stc;
        end
    end

    // ================================================================ counters (free running)
    reg [31:0] fcnt;                        // frames done since power-up
    reg [23:0] n_runs, n_gl, n_c0;
    reg [15:0] n_fd, n_er, n_tel, n_rel, n_pin, n_lost;
    reg [7:0]  n_ref;
    reg        lost_p;                      // pulse: a record had to be dropped (any producer)
    reg        ref_p;                       // pulse: a trigger was refused
    always @(posedge clk) begin
        if (rst) begin
            fcnt <= 32'd0; n_runs <= 24'd0; n_gl <= 24'd0; n_c0 <= 24'd0; n_fd <= 16'd0; n_er <= 16'd0;
            n_tel <= 16'd0; n_rel <= 16'd0; n_pin <= 16'd0; n_lost <= 16'd0; n_ref <= 8'd0;
        end else begin
            if (fd_t) begin fcnt <= fcnt + 32'd1; n_fd <= n_fd + 16'd1; end
            if (rv_t) n_runs <= n_runs + 24'd1;
            if (rv_t && gl_t) n_gl <= n_gl + 24'd1;
            if (sv_t && sym_t == 2'd0) n_c0 <= n_c0 + 24'd1;
            if (er_t) n_er <= n_er + 16'd1;
            if (tel_t) n_tel <= n_tel + 16'd1;
            if (rel_t) n_rel <= n_rel + 16'd1;
            if (pin_t) n_pin <= n_pin + 16'd1;
            if (lost_p) n_lost <= n_lost + 16'd1;
            if (ref_p) n_ref <= n_ref + 8'd1;
        end
    end

    // ================================================================ edges, dark, the laptop
    reg [31:0] last_edge;                   // time of the last edge
    reg [31:0] gap_us;                      // microseconds since it (saturating)
    reg [15:0] gap_ms;                      // milliseconds since it (saturating)
    reg        stopped;                     // no edge for STOP_US
    reg        seen_edge;                   // an edge since power-up
    reg        was_dark;                    // the line was dark for the wake time
    reg [31:0] maxgap;                      // the longest gap in this STATUS interval
    reg        attached;
    reg [15:0] dark_ms, cold_ms, att_left;
    reg        hold_dark;                   // held because dark (else: the cold-start hold)
    reg [15:0] cold_left;
    wire [15:0] dark_eff = (attached && dark_ms != 16'd0) ? dark_ms : DARK_DEF_MS[15:0];
    reg        st_freeze;                   // a STATUS is being taken: its interval values hold still

    // the laptop's commands
    wire        k_ok; wire [7:0] k_cmd; wire [55:0] k_p;
    diag_cmd #(.DIV(DIV), .TOUT(CMD_TOUT)) u_cmd (.clk(clk), .rst(rst), .rxd(rxd), .ok(k_ok), .cmd(k_cmd), .p(k_p));
    wire [15:0] k_p01 = {k_p[47:40], k_p[55:48]};     // P0, P1 little endian
    wire [15:0] k_p23 = {k_p[31:24], k_p[39:32]};
    wire        k_keep = k_ok && k_cmd == 8'h13;

    // events raised here (see the event table)
    reg ev_dark, ev_stop, ev_back, ev_cold, ev_att, ev_gone;
    reg [31:0] ev_back_arg;
    always @(posedge clk) begin
        ev_dark <= 1'b0; ev_stop <= 1'b0; ev_back <= 1'b0; ev_cold <= 1'b0; ev_att <= 1'b0; ev_gone <= 1'b0;
        if (rst) begin
            last_edge <= 32'd0; gap_us <= 32'd0; gap_ms <= 16'd0; stopped <= 1'b0; seen_edge <= 1'b0;
            was_dark <= 1'b0; maxgap <= 32'd0; attached <= 1'b0; dark_ms <= 16'd0; cold_ms <= 16'd0;
            att_left <= 16'd0; hold <= 1'b0; hold_dark <= 1'b0; cold_left <= 16'd0; ev_back_arg <= 32'd0;
        end else begin
            if (rv_t) begin
                last_edge <= now; gap_us <= 32'd0; gap_ms <= 16'd0; seen_edge <= 1'b1; was_dark <= 1'b0;
                if (stopped) begin ev_back <= 1'b1; ev_back_arg <= gap_us; end
                stopped <= 1'b0;
            end else begin
                if (us && gap_us != 32'hFFFF_FFFF) gap_us <= gap_us + 32'd1;
                if (ms && gap_ms != 16'hFFFF) gap_ms <= gap_ms + 16'd1;
                if (gap_us == STOP_US && !stopped) begin stopped <= 1'b1; ev_stop <= 1'b1; end
                if (gap_ms >= dark_eff && dark_eff != 16'd0) was_dark <= 1'b1;
            end
            if (done[1]) maxgap <= 32'd0;
            else if (!st_freeze && gap_us > maxgap) maxgap <= gap_us;

            // the laptop: attached while its keepalive comes
            if (k_keep) begin
                dark_ms <= k_p01; cold_ms <= k_p23; att_left <= ATTACH_MS[15:0];
                if (!attached) ev_att <= 1'b1;
                attached <= 1'b1;
            end else if (attached && ms) begin
                if (att_left == 16'd0) begin attached <= 1'b0; ev_gone <= 1'b1; end
                else att_left <= att_left - 16'd1;
            end

            // the core held: dark for DARK ms, then COLD ms more from the first edge
            if (!attached) begin
                hold <= 1'b0; hold_dark <= 1'b0;
            end else if (dark_ms != 16'd0 && gap_ms >= dark_ms && !rv_t && !(hold && hold_dark)) begin
                if (!hold) ev_dark <= 1'b1;
                hold <= 1'b1; hold_dark <= 1'b1;
            end else if (hold && hold_dark && rv_t) begin
                hold_dark <= 1'b0; cold_left <= cold_ms;
            end else if (hold && !hold_dark && ms) begin
                if (cold_left == 16'd0) begin hold <= 1'b0; ev_cold <= 1'b1; end
                else cold_left <= cold_left - 16'd1;
            end
        end
    end

    // ================================================================ capture triggers
    reg        lk_d, run_d, bk_d, pk_d, ovr_d;
    always @(posedge clk) begin lk_d <= lk_t; run_d <= run_t; bk_d <= bk_t; pk_d <= pk_t; ovr_d <= ovr_t; end
    reg [15:0] wake2_left;                  // ms to the steady-line capture (0: none due)
    reg [15:0] lock_ms, unl_since, pos_since, pos_left;
    reg        unl_ever, pos_ever, pos_armed;
    reg        pos_z;                       // pos_left == 0, kept with it: the compare off the count's path
    reg [1:0]  pos_s;
    reg        t_wake, t_wake2, t_unl, t_pos, t_pcr, t_pcf;   // pending trigger requests
    reg        trig, trig_fr;
    reg [2:0]  trig_cause;
    // a stream's input is non-zero this frame (at the engine's start; in_w holds still then)
    reg        nz_q;
    always @(posedge clk)
        nz_q <= (pos_s == 2'd0) ? |in_w[143:96] : (pos_s == 2'd1) ? |in_w[95:48] : |in_w[47:0];
    reg        es_d;
    always @(posedge clk) es_d <= es_t;
    always @(posedge clk) begin
        trig <= 1'b0;
        if (rst) begin
            wake2_left <= 16'd0; lock_ms <= 16'd0; unl_since <= 16'd0; pos_since <= 16'd0; pos_left <= 16'd0;
            unl_ever <= 1'b0; pos_ever <= 1'b0; pos_armed <= 1'b0; pos_s <= 2'd0; pos_z <= 1'b1;
            t_wake <= 1'b0; t_wake2 <= 1'b0; t_unl <= 1'b0; t_pos <= 1'b0; t_pcr <= 1'b0; t_pcf <= 1'b0;
            trig_fr <= 1'b0; trig_cause <= 3'd0;
        end else begin
            // wake: the first edge after power-up, or after the line was dark
            if (rv_t && (!seen_edge || was_dark)) begin t_wake <= 1'b1; wake2_left <= WAKE2_MS[15:0]; end
            else if (ms && wake2_left != 16'd0) begin
                if (wake2_left == 16'd1) t_wake2 <= 1'b1;
                wake2_left <= wake2_left - 16'd1;
            end
            // unlock: after lock held UNLOCK_HOLD_MS, not by the hold, one in UNLOCK_GAP_MS
            if (!lk_t) lock_ms <= 16'd0;
            else if (ms && lock_ms != 16'hFFFF) lock_ms <= lock_ms + 16'd1;
            if (ms && unl_since != 16'hFFFF) unl_since <= unl_since + 16'd1;
            if (lk_d && !lk_t && !hold && lock_ms >= UNLOCK_HOLD_MS && (!unl_ever || unl_since >= UNLOCK_GAP_MS)) begin
                t_unl <= 1'b1; unl_ever <= 1'b1; unl_since <= 16'd0;
            end
            // a new position: a command 01 that turns a stream on, then that stream's audio
            if (ms && pos_since != 16'hFFFF) pos_since <= pos_since + 16'd1;
            if (cok_t && cmd_t == 8'h01 && cp_t[49:48] != 2'd0) begin
                pos_armed <= 1'b1; pos_s <= cp_t[53:52]; pos_left <= POS_WAIT_MS[15:0];
                pos_z <= POS_WAIT_MS[15:0] == 16'd0;
            end else if (pos_armed) begin
                if (es_d && nz_q) begin
                    pos_armed <= 1'b0;
                    if (!pos_ever || pos_since >= POS_GAP_MS) begin t_pos <= 1'b1; pos_ever <= 1'b1; pos_since <= 16'd0; end
                end else if (ms) begin
                    // pos_z, not a compare of pos_left here: the compare deciding all 16 bits' next
                    // value was the build's slowest path (7.3 % margin, 2026-10-04)
                    if (pos_z) pos_armed <= 1'b0;
                    else begin pos_left <= pos_left - 16'd1; pos_z <= pos_left == 16'd1; end
                end
            end
            // the laptop
            if (k_ok && k_cmd == 8'h10) begin
                if (k_p[48]) t_pcf <= 1'b1; else t_pcr <= 1'b1;
            end
            // one trigger a clock, in this order
            if (t_wake)       begin trig <= 1'b1; trig_fr <= 1'b0; trig_cause <= 3'd1; t_wake  <= 1'b0; end
            else if (t_wake2) begin trig <= 1'b1; trig_fr <= 1'b0; trig_cause <= 3'd2; t_wake2 <= 1'b0; end
            else if (t_unl)   begin trig <= 1'b1; trig_fr <= 1'b0; trig_cause <= 3'd3; t_unl   <= 1'b0; end
            else if (t_pos)   begin trig <= 1'b1; trig_fr <= 1'b1; trig_cause <= 3'd4; t_pos   <= 1'b0; end
            else if (t_pcr)   begin trig <= 1'b1; trig_fr <= 1'b0; trig_cause <= 3'd5; t_pcr   <= 1'b0; end
            else if (t_pcf)   begin trig <= 1'b1; trig_fr <= 1'b1; trig_cause <= 3'd6; t_pcf   <= 1'b0; end
        end
    end

    // ================================================================ the capture buffer
    reg        gpend;                       // the two-edge flag belongs to the run after its word
    always @(posedge clk) gpend <= rst ? 1'b0 : (rv_t ? gl_t : gpend);
    wire [8:0] run_e = {gpend, rl_t, rlen_t > 8'd127 ? 7'd127 : rlen_t[6:0]};
    wire [8:0] frm_e = {ba_t == 6'd0, bd_t};
    wire [1:0] cap_state; wire cap_fm;
    wire       c_evt, c_evr, c_evd, c_evn; wire [3:0] c_atrig; wire [2:0] c_aref; wire [16:0] c_adump;
    wire [15:0] c_adone;
    wire       pkt_ready; reg pkt_take; wire [15:0] pkt_n; wire [287:0] pkt;
    wire [31:0] tr_entries, tr_before; wire [2:0] tr_cause; wire tr_frames;
    diag_cap #(.NBW(CAP_NBW), .BW(CAP_BW), .RUN_MS(CAP_RUN_MS), .FRM_MS(CAP_FRM_MS)) u_cap (
        .clk(clk), .rst(rst), .ms(ms), .run_v(rv_t), .run_e(run_e), .frm_v(bwe_t), .frm_e(frm_e),
        .trig(trig), .trig_cause(trig_cause), .trig_frames(trig_fr), .state(cap_state), .frames_mode(cap_fm),
        .ev_trig(c_evt), .ev_refused(c_evr), .ev_dump(c_evd), .ev_done(c_evn),
        .a_trig(c_atrig), .a_ref(c_aref), .a_dump(c_adump), .a_done(c_adone),
        .pkt_ready(pkt_ready), .pkt_take(pkt_take), .pkt_n(pkt_n), .pkt(pkt),
        .tr_entries(tr_entries), .tr_before(tr_before), .tr_cause(tr_cause), .tr_frames(tr_frames));
    always @(posedge clk) ref_p <= c_evr;

    // ================================================================ 0 BLOCK
    // the control bytes: two banks in a small RAM, the block being collected in one, the record
    // being sent read from the other; a byte not written in its block reads as 0
    reg  [7:0]  cbram [0:63];
    reg         wbank, rbank;
    reg  [31:0] cmask0, cmask1;
    reg  [15:0] fmask, pmask, lkmask;
    reg  [7:0]  b63or, b63and, b63_cur;
    reg  [3:0]  bdor, bdand, bd_cur;
    reg  [3:0]  last_bi;
    reg  [31:0] last_us, last_cnt;
    reg  [3:0]  last_fl;                    // {sense, known, bk, lk} at the block's last frame done
    reg  [15:0] last_ui;
    reg         s_drop, s_tel, s_hit;       // the decoder's verdict on the block, sticky
    reg  [4:0]  bdly;                       // clocks to the load after frame 15
    reg         r0;
    reg  [159:0] bh;                        // the record's header, as taken
    // the next block began (its byte 0 with frames collected and an index not above the last), or
    // the line stopped with frames collected. The compares are taken a clock ahead (bi_t <= last_bi
    // and fmask != 0 -> part -> 300 enables were slowest paths, 2026-10-04): bi_t and fmask hold
    // still for hundreds of clocks round a byte 0 (bi_t from the preamble on, fmask from the last
    // frame's end) and for STOP_US before the line is called stopped; ba0_t is ba_t's own compare
    reg         bi_le_q, fm_nz_q;
    always @(posedge clk) begin bi_le_q <= bi_t <= last_bi; fm_nz_q <= fmask != 16'd0; end
    wire        part_b = bwe_t && ba0_t && fm_nz_q && bi_le_q;
    wire        part_s = ev_stop && fm_nz_q && bdly == 5'd0;
    wire        part = part_b || part_s;
    wire        load0 = (bdly == 5'd1 && !fd_t) || part;
    wire [4:0]  cbi = {bi_t, ba_t == 6'd62};
    always @(posedge clk) if (bwe_t && (ba_t == 6'd61 || ba_t == 6'd62)) cbram[{wbank, cbi}] <= bd_t;
    always @(posedge clk) begin
        lost0 <= 1'b0;
        if (rst) begin
            fmask <= 16'd0; pmask <= 16'd0; lkmask <= 16'd0; b63or <= 8'd0; b63and <= 8'hFF; b63_cur <= 8'd0;
            bdor <= 4'd0; bdand <= 4'hF; bd_cur <= 4'd0; last_bi <= 4'd0; last_us <= 32'd0; last_cnt <= 32'd0;
            last_fl <= 4'd0; last_ui <= 16'd0; s_drop <= 1'b0; s_tel <= 1'b0; s_hit <= 1'b0; bdly <= 5'd0;
            r0 <= 1'b0; bh <= 160'd0; wbank <= 1'b0; rbank <= 1'b0; cmask0 <= 32'd0; cmask1 <= 32'd0;
        end else begin
            if (done[0]) r0 <= 1'b0;
            if (drop_t) s_drop <= 1'b1;
            if (tel_t)  s_tel  <= 1'b1;
            if (hit_t)  s_hit  <= 1'b1;
            if (bwe_t && (ba_t == 6'd61 || ba_t == 6'd62)) begin
                if (wbank) cmask1[cbi] <= 1'b1; else cmask0[cbi] <= 1'b1;
            end
            if (bwe_t && ba_t == 6'd63) b63_cur <= bd_t;
            if (bwe_t && ba_t == 6'd0)  bd_cur  <= bd_t[3:0];
            if (fd_t) begin
                fmask  <= fmask  | (16'd1 << bi_t);
                pmask  <= pmask  | ({15'd0, fpar_t} << bi_t);
                lkmask <= lkmask | ({15'd0, lk_t} << bi_t);
                b63or  <= b63or | b63_cur; b63and <= b63and & b63_cur;
                bdor   <= bdor | bd_cur;   bdand  <= bdand & bd_cur;
                last_bi <= bi_t; last_us <= now; last_cnt <= fcnt + 32'd1; last_fl <= {ps_t, pk_t, bk_t, lk_t};
                last_ui <= ui_t;
                if (bi_t == 4'd15) begin bdly <= BLK_DELAY[4:0]; s_drop <= drop_t; s_tel <= 1'b0; s_hit <= 1'b0; end
            end else if (bdly != 5'd0) begin
                bdly <= bdly - 5'd1;
            end
            // the record: frame 15 + BLK_DELAY, or a block that ended without frame 15
            if (load0) begin
                if (r0) begin
                    lost0 <= 1'b1;                       // the last one is still going out: this one is lost
                    if (wbank) cmask1 <= 32'd0; else cmask0 <= 32'd0;
                end else begin
                    r0 <= 1'b1; rbank <= wbank; wbank <= ~wbank;
                    if (wbank) cmask0 <= 32'd0; else cmask1 <= 32'd0;
                    bh <= {last_ui, bdor, bdand, b63and, b63or, lkmask, pmask, fmask,
                           part, part ? 3'b000 : {s_hit, s_tel, s_drop}, last_fl, last_cnt, last_us};
                end
                fmask <= 16'd0; pmask <= 16'd0; lkmask <= 16'd0; b63or <= 8'd0; b63and <= 8'hFF;
                bdor <= 4'd0; bdand <= 4'hF; bdly <= 5'd0;
                if (part_b) bd_cur <= bd_t[3:0];
            end
        end
    end
    // the record, a byte at a time: the header's lane (bytes 0..22) or the control byte from the
    // RAM (23..54), then the byte
    wire [255:0] h0 = {96'd0, bh, 8'h00, 8'h5A, 8'hA5};
    wire [5:0]  cb_i = wi[5:0] - 6'd23;
    wire [31:0] rmask = rbank ? cmask1 : cmask0;
    reg  [63:0] ln0; reg [7:0] cb_q0; reg hd0;
    always @(posedge clk) begin
        ln0   <= h0[64 * wi[4:3] +: 64];
        cb_q0 <= rmask[cb_i[4:0]] ? cbram[{rbank, cb_i[4:0]}] : 8'd0;
        hd0   <= wi < 8'd23;
        ob0   <= hd0 ? ln0[8 * wi_d[2:0] +: 8] : cb_q0;
    end
    assign req[0] = r0;

    // ================================================================ 1 STATUS
    // The counters, the state and the slow taps are taken in one clock; the interval values
    // (the eye, the gap, the peaks, the activity) are read as the record goes out and hold still
    // until it has, then start anew.
    reg  [7:0]   cmin [0:3], cmax [0:3];    // class 1 HIGH, class 2 HIGH, class 1 LOW, class 2 LOW
    reg  [15:0]  emin, emax;
    reg  [11:0]  odd_sig;
    reg  [63:0]  chmask;
    reg  [7:0]   prevb [0:63];
    reg          ch_v; reg [5:0] ch_a; reg [7:0] ch_d;
    reg          ch_x; reg [5:0] ch_xa;      // the compare, registered: the bit is set a clock later
    reg  [63:0]  seen;                      // the byte was written since power-up: only then is prevb its
                                            // last value (on the chip prevb starts at 0, in a simulation X)
    reg  [3:0]   pk_n;                      // channels still to take this frame
    reg  [2:0]   pk_i, pk_i1, pk_i2;        // the channel at each step
    reg          pk_v1, pk_v2;
    reg  [23:0]  pk_ch;                     // step 1: the channel's sample
    reg  [15:0]  pk_a;                      // step 2: |sample| >> 8
    reg  [15:0]  pkr [0:7];                 // peaks: s0 L R, s1 L R, s2 L R, out L R
    reg          st_pend, r1;
    reg  [175:0] sn_cnt;
    reg  [15:0]  sn_st, sn_ui, sn_b, sn_dark, sn_cold;
    reg  [13:0]  sn_ds;
    reg  [11:0]  sn_cs;
    reg  [31:0]  sn_now, sn_per;
    wire signed [31:0] e_s = err_t;
    wire [15:0] e16 = (e_s > 32'sd32767) ? 16'h7FFF : (e_s < -32'sd32768) ? 16'h8000 : err_t[15:0];
    wire [1:0]  cidx = {~sl_t, sym_t == 2'd2};
    wire [23:0] pk_abs = pk_ch[23] ? (24'd0 - pk_ch) : pk_ch;
    // pk_a against every channel's peak at once: picking pkr[pk_i2] first and comparing after was
    // a slowest path (2026-10-04); the channel now only selects which compare is written
    reg  [7:0]   pk_gt;
    integer      ipk;
    always @* for (ipk = 0; ipk < 8; ipk = ipk + 1) pk_gt[ipk] = pk_a > pkr[ipk];
    wire        pk_busy = pk_n != 4'd0 || pk_v1 || pk_v2;
    always @(posedge clk) st_freeze <= r1;
    always @(posedge clk) begin
        lost1 <= 1'b0; st_load <= 1'b0;
        // the byte activity mask: a byte that differs from the same byte a frame ago. The read
        // of prevb and the compare take one clock, the mask bit's decode and set the next (the
        // two in one clock were the build's slowest path, 1.9 % margin on 2026-10-04)
        ch_v <= bwe_t; ch_a <= ba_t; ch_d <= bd_t;
        ch_x <= ch_v && seen[ch_a] && prevb[ch_a] != ch_d; ch_xa <= ch_a;
        if (ch_v) begin prevb[ch_a] <= ch_d; seen[ch_a] <= 1'b1; end
        if (ch_x && !st_freeze) chmask[ch_xa] <= 1'b1;
        if (rst) begin
            for (i1 = 0; i1 < 4; i1 = i1 + 1) begin cmin[i1] <= 8'hFF; cmax[i1] <= 8'd0; end
            emin <= 16'h7FFF; emax <= 16'h8000; odd_sig <= 12'd0; chmask <= 64'd0; pk_n <= 4'd0; seen <= 64'd0;
            pk_i <= 3'd0; pk_i1 <= 3'd0; pk_i2 <= 3'd0; pk_v1 <= 1'b0; pk_v2 <= 1'b0; pk_ch <= 24'd0; pk_a <= 16'd0;
            for (i1 = 0; i1 < 8; i1 = i1 + 1) pkr[i1] <= 16'd0;
            st_pend <= 1'b0; r1 <= 1'b0; sn_cnt <= 176'd0; sn_st <= 16'd0; sn_ui <= 16'd0;
            sn_dark <= 16'd0; sn_cold <= 16'd0; sn_ds <= 14'd0; sn_cs <= 12'd0;
            sn_b <= 16'd0; sn_now <= 32'd0; sn_per <= 32'd0;
        end else begin
            if (done[1]) begin
                r1 <= 1'b0;
                for (i1 = 0; i1 < 4; i1 = i1 + 1) begin cmin[i1] <= 8'hFF; cmax[i1] <= 8'd0; end
                emin <= e16; emax <= e16; chmask <= 64'd0;
                for (i1 = 0; i1 < 8; i1 = i1 + 1) pkr[i1] <= 16'd0;
            end else if (!st_freeze) begin
                if (sv_t && (sym_t == 2'd1 || sym_t == 2'd2)) begin
                    if (sraw_t < cmin[cidx]) cmin[cidx] <= sraw_t;
                    if (sraw_t > cmax[cidx]) cmax[cidx] <= sraw_t;
                end
                if ($signed(e16) < $signed(emin)) emin <= e16;
                if ($signed(e16) > $signed(emax)) emax <= e16;
                if (pre_t && psig_t != csig_t) odd_sig <= psig_t;
            end
            // peaks, one channel a clock after the engine's start (in_w and out_w hold still then)
            // three steps a channel: the sample, its magnitude, the compare
            pk_v1 <= pk_n != 4'd0; pk_v2 <= pk_v1; pk_i1 <= pk_i; pk_i2 <= pk_i1;
            if (es_t && !pk_busy && !r1) begin
                pk_n <= 4'd8; pk_i <= 3'd0;
            end else if (pk_n != 4'd0) begin
                pk_n <= pk_n - 4'd1; pk_i <= pk_i + 3'd1;
            end
            case (pk_i)
                3'd0: pk_ch <= in_w[143:120]; 3'd1: pk_ch <= in_w[119:96];
                3'd2: pk_ch <= in_w[95:72];   3'd3: pk_ch <= in_w[71:48];
                3'd4: pk_ch <= in_w[47:24];   3'd5: pk_ch <= in_w[23:0];
                3'd6: pk_ch <= out_w[47:24];  default: pk_ch <= out_w[23:0];
            endcase
            pk_a <= pk_abs[23:8];
            for (i1 = 0; i1 < 8; i1 = i1 + 1)
                if (pk_v2 && pk_i2 == i1 && pk_gt[i1]) pkr[i1] <= pk_a;
            if (st_tick) st_pend <= 1'b1;
            if (st_pend && !pk_busy && !(es_t && !r1)) begin
                st_pend <= 1'b0;
                if (r1) lost1 <= 1'b1;
                else begin
                    r1 <= 1'b1; st_load <= 1'b1;
                    sn_cnt <= {n_ref, n_lost, n_pin, n_rel, n_tel, n_er, n_fd, n_c0, n_gl, n_runs};
                    sn_st  <= {2'b00, cap_fm, cap_state, hold, attached, ps_t,
                               stopped, ovr_t, pk_t, r48_t, perok_t, run_t, bk_t, lk_t};
                    sn_now <= now; sn_ui <= ui_t; sn_b <= b_t; sn_per <= per_t;
                    sn_ds <= ds_t; sn_cs <= csig_t;
                    sn_dark <= attached ? dark_ms : 16'd0; sn_cold <= attached ? cold_ms : 16'd0;
                end
            end
        end
    end
    // the record, a byte at a time (LOGGING.md, STATUS)
    wire [767:0] rec1 = {24'd0, sn_cold, sn_dark, {2'b00, sn_ds}, chmask,
                         pkr[7], pkr[6], pkr[5], pkr[4], pkr[3], pkr[2], pkr[1], pkr[0],
                         emax, emin, sn_per, {4'd0, odd_sig}, {4'd0, sn_cs}, maxgap,
                         cmax[3], cmin[3], cmax[2], cmin[2], cmax[1], cmin[1], cmax[0], cmin[0],
                         sn_b, sn_ui, sn_cnt, BUILD_ID, sn_st, sn_now, 8'h00, 8'h57, 8'hA5};
    reg  [63:0] ln1;
    always @(posedge clk) begin
        ln1 <= rec1[64 * wi1[6:3] +: 64];
        ob1 <= ln1[8 * wi_d[2:0] +: 8];
    end
    assign req[1] = r1;

    // ================================================================ 2 SET
    localparam [31:0] W_ONE = 32'h1000_0000, W_1MK = 32'h0FF0_0000;
    wire        w03  = cok_t && cmd_t == 8'h03;
    wire [5:0]  wa   = cp_t[53:48];
    wire [31:0] wv   = cp_t[47:16];
    wire [7:0]  wf   = cp_t[15:8];
    wire [7:0]  wt   = cp_t[7:0];
    reg  [5:0]  s_next; reg [2:0] s_m5; reg [7:0] s_tag; reg s_ord, s_cst, s_skip; reg [31:0] s_ts, s_l;
    reg  [31:0] g0, g1, g2;
    reg  [2:0]  s_fl;
    reg         r2;
    wire [31:0] w_exp = (s_m5 == 3'd0) ? W_ONE : 32'd0;
    always @(posedge clk) begin
        lost2 <= 1'b0;
        if (rst) begin
            s_next <= 6'd0; s_m5 <= 3'd0; s_tag <= 8'd0; s_ord <= 1'b0; s_cst <= 1'b0; s_skip <= 1'b1; s_ts <= 32'd0;
            s_l <= 32'd0; g0 <= 32'd0; g1 <= 32'd0; g2 <= 32'd0; s_fl <= 3'd0; r2 <= 1'b0;
        end else begin
            if (done[2]) r2 <= 1'b0;
            if (w03) begin
                if (wa == 6'd0) begin
                    // a new set; while the last one is still going out its fields must hold: lost
                    if (r2 && !done[2]) begin s_skip <= 1'b1; lost2 <= 1'b1; end
                    else begin
                        s_skip <= 1'b0; s_ts <= now; s_tag <= wt; s_ord <= 1'b1; s_next <= 6'd1; s_m5 <= 3'd1;
                        s_cst <= wv == W_ONE && wf == 8'd0;
                    end
                end else if (!s_skip) begin
                    s_next <= wa + 6'd1;
                    s_m5 <= (s_m5 == 3'd4) ? 3'd0 : s_m5 + 3'd1;
                    if (wa != s_next || wt != s_tag) s_ord <= 1'b0;
                    if (wa < 6'd40 && (wv != w_exp || wf != 8'd0)) s_cst <= 1'b0;
                    if (wa >= 6'd40 && wa <= 6'd45) begin
                        if (!wa[0]) s_l <= wv;
                        else if (wv != s_l) s_cst <= 1'b0;
                        if (wf != 8'd0) s_cst <= 1'b0;
                    end
                    if (wa == 6'd40) g0 <= wv;
                    if (wa == 6'd42) g1 <= wv;
                    if (wa == 6'd44) g2 <= wv;
                    if (wa == 6'd46) begin
                        s_skip <= 1'b1;
                        r2 <= 1'b1;
                        s_fl <= {s_cst && wv == W_1MK && wf == 8'h01, s_ord && wa == s_next && wt == s_tag, wf[0]};
                    end
                end
            end
        end
    end
    wire [191:0] rec2 = {24'd0, g2, g1, g0, {5'd0, s_fl}, s_tag, s_ts, 8'h00, 8'h53, 8'hA5};
    reg  [63:0] ln2;
    always @(posedge clk) begin
        ln2 <= rec2[64 * wi[4:3] +: 64];
        ob2 <= ln2[8 * wi_d[2:0] +: 8];
    end
    assign req[2] = r2;

    // ================================================================ 3 CMD (command 01), a queue of 4
    reg  [87:0] cq [0:3];                   // {ts, p}
    reg  [2:0]  cq_n; reg [1:0] cq_w, cq_r;
    wire        push = cok_t && cmd_t == 8'h01;
    always @(posedge clk) begin
        lost3 <= 1'b0;
        if (rst) begin
            cq_n <= 3'd0; cq_w <= 2'd0; cq_r <= 2'd0;
        end else begin
            if (push) begin
                if (cq_n == 3'd4) lost3 <= 1'b1;
                else begin cq[cq_w] <= {now, cp_t}; cq_w <= cq_w + 2'd1; end
            end
            if (done[3]) cq_r <= cq_r + 2'd1;
            cq_n <= cq_n + ((push && cq_n != 3'd4) ? 3'd1 : 3'd0) - (done[3] ? 3'd1 : 3'd0);
        end
    end
    wire [87:0] ch = cq[cq_r];
    wire [127:0] rec3 = {8'd0, ch[7:0], ch[15:8], ch[23:16], ch[31:24], ch[39:32], ch[47:40], ch[55:48],
                         8'h01, ch[87:56], 8'h00, 8'h3C, 8'hA5};
    reg  [63:0] ln3;
    always @(posedge clk) begin
        ln3 <= rec3[64 * wi[3] +: 64];
        ob3 <= ln3[8 * wi_d[2:0] +: 8];
    end
    assign req[3] = cq_n != 3'd0;

    // ================================================================ 4 EVENT, slots into a queue
    // slot: lock 01/02, block 03/04, train 05/06, parity 07/08, dark 09, edges 0A/0B, cold 0C,
    // capture 10, dump 11, done 12, refused 13, commit 14/15, bank 16, overrun 17, mark 20,
    // command 21, laptop 22/23, power-up 30. A slot goes into the queue at most once a ms: its
    // first event of a ms is pushed at once, the rest of that ms only counted; a slot that counted
    // any is pushed once more when its ms is up, as it is then (a state slot: the state it ended
    // in) and with the count, so the trail always ends on the true state. The code and argument
    // are taken when the slot is pushed, a few clocks after the event at most; the time too.
    localparam NS = 18;
    reg  [NS-1:0] raise;
    reg  [NS-1:0] pend, sent, flush;
    reg  [7:0]    cnt [0:NS-1];
    reg           cm_ok_h; reg [7:0] cm_tag_h;       // a commit's outcome and tag, held from its pulse
    reg           boot;
    always @* begin
        raise = {NS{1'b0}};
        raise[0]  = lk_t != lk_d;
        raise[1]  = bk_t != bk_d;
        raise[2]  = run_t != run_d;
        raise[3]  = pk_t != pk_d;
        raise[4]  = ev_dark;
        raise[5]  = ev_stop | ev_back;
        raise[6]  = ev_cold;
        raise[7]  = c_evt;
        raise[8]  = c_evd;
        raise[9]  = c_evn;
        raise[10] = c_evr;
        raise[11] = cmok_t | cmbad_t;
        raise[12] = bsw_t;
        raise[13] = ovr_t && !ovr_d;
        raise[14] = k_ok && k_cmd == 8'h11;
        raise[15] = k_ok;
        raise[16] = ev_att | ev_gone;
        raise[17] = boot;
    end
    // a slot's code and argument as they are now
    reg  [7:0]  s_code [0:NS-1];
    reg  [31:0] s_arg  [0:NS-1];
    always @* begin
        s_code[0]  = lk_t ? 8'h01 : 8'h02;          s_arg[0]  = fcnt;
        s_code[1]  = bk_t ? 8'h03 : 8'h04;          s_arg[1]  = fcnt;
        s_code[2]  = run_t ? 8'h05 : 8'h06;         s_arg[2]  = fcnt;
        s_code[3]  = pk_t ? 8'h07 : 8'h08;          s_arg[3]  = {ps_t, fcnt[30:0]};
        s_code[4]  = 8'h09;                         s_arg[4]  = last_edge;
        s_code[5]  = stopped ? 8'h0A : 8'h0B;       s_arg[5]  = stopped ? last_edge : ev_back_arg;
        s_code[6]  = 8'h0C;                         s_arg[6]  = {16'd0, cold_ms};
        s_code[7]  = 8'h10;                         s_arg[7]  = {28'd0, c_atrig};
        s_code[8]  = 8'h11;                         s_arg[8]  = {15'd0, c_adump};
        s_code[9]  = 8'h12;                         s_arg[9]  = {16'd0, c_adone};
        s_code[10] = 8'h13;                         s_arg[10] = {29'd0, c_aref};
        s_code[11] = cm_ok_h ? 8'h14 : 8'h15;       s_arg[11] = {24'd0, cm_tag_h};
        s_code[12] = 8'h16;                         s_arg[12] = 32'd0;
        s_code[13] = 8'h17;                         s_arg[13] = fcnt;
        s_code[14] = 8'h20;                         s_arg[14] = {16'd0, k_p01};
        s_code[15] = 8'h21;                         s_arg[15] = {8'd0, k_p[47:40], k_p[55:48], k_cmd};
        s_code[16] = attached ? 8'h22 : 8'h23;      s_arg[16] = {cold_ms, dark_ms};
        s_code[17] = 8'h30;                         s_arg[17] = BUILD_ID;
    end
    // the push: the lowest pending slot, picked one clock, its record into the queue the next
    reg  [NS-1:0] go_now;
    always @* begin
        go_now = {NS{1'b0}};
        for (i3 = NS - 1; i3 >= 0; i3 = i3 - 1)
            if (pend[i3]) go_now = {{(NS-1){1'b0}}, 1'b1} << i3;
    end
    reg  [NS-1:0] ps_oh;
    reg           ps_v;
    reg  [7:0]    m_code, m_cnt; reg [31:0] m_arg;
    always @* begin
        m_code = 8'd0; m_cnt = 8'd0; m_arg = 32'd0;
        for (i4 = 0; i4 < NS; i4 = i4 + 1)
            if (ps_oh[i4]) begin m_code = m_code | s_code[i4]; m_cnt = m_cnt | cnt[i4]; m_arg = m_arg | s_arg[i4]; end
    end
    reg  [79:0] evq [0:15];                 // {arg, cnt, code, time}
    reg  [3:0]  eq_w, eq_r;
    reg  [4:0]  eq_n;
    reg         lost4;
    wire        eq_pop = done[4];
    // a slot's next state: the ms's end first (a slot that counted goes again), then a pick, then
    // an event now (the first of a ms goes; any other is counted)
    reg  [NS-1:0] pend_n, sent_n, flush_n, cinc;
    always @* begin
        for (i9 = 0; i9 < NS; i9 = i9 + 1) begin
            sent_n[i9] = ms ? 1'b0 : sent[i9];
            pend_n[i9] = pend[i9]; flush_n[i9] = flush[i9]; cinc[i9] = 1'b0;
            if (ms && flush[i9]) begin pend_n[i9] = 1'b1; flush_n[i9] = 1'b0; sent_n[i9] = 1'b1; end
            if (!ps_v && go_now[i9]) pend_n[i9] = 1'b0;
            if (raise[i9]) begin
                if (!sent_n[i9] && !pend_n[i9]) begin pend_n[i9] = 1'b1; sent_n[i9] = 1'b1; end
                else begin cinc[i9] = flush_n[i9]; flush_n[i9] = 1'b1; end
            end
        end
    end
    wire        eq_push = ps_v && eq_n != 5'd16;
    always @(posedge clk) if (eq_push) evq[eq_w] <= {m_arg, m_cnt, m_code, now};
    always @(posedge clk) begin
        lost4 <= 1'b0;
        if (rst) begin
            pend <= {NS{1'b0}}; sent <= {NS{1'b0}}; flush <= {NS{1'b0}}; ps_oh <= {NS{1'b0}}; ps_v <= 1'b0;
            eq_w <= 4'd0; eq_r <= 4'd0; eq_n <= 5'd0; boot <= 1'b1; cm_ok_h <= 1'b0; cm_tag_h <= 8'd0;
            for (i5 = 0; i5 < NS; i5 = i5 + 1) cnt[i5] <= 8'd0;
        end else begin
            boot <= 1'b0;
            if (cmok_t | cmbad_t) begin cm_ok_h <= cmok_t; cm_tag_h <= ctag_t; end
            // the queue
            if (ps_v && eq_n == 5'd16) lost4 <= 1'b1;
            if (eq_push) eq_w <= eq_w + 4'd1;
            if (eq_pop) eq_r <= eq_r + 4'd1;
            eq_n <= eq_n + (eq_push ? 5'd1 : 5'd0) - (eq_pop ? 5'd1 : 5'd0);
            // the pick
            ps_v <= 1'b0;
            if (!ps_v && go_now != {NS{1'b0}}) begin ps_oh <= go_now; ps_v <= 1'b1; end
            pend <= pend_n; sent <= sent_n; flush <= flush_n;
            for (i5 = 0; i5 < NS; i5 = i5 + 1) begin
                if (ps_v && ps_oh[i5]) cnt[i5] <= 8'd0;
                else if (cinc[i5] && cnt[i5] != 8'hFF) cnt[i5] <= cnt[i5] + 8'd1;
            end
        end
    end
    wire [79:0] eh = evq[eq_r];
    wire [127:0] rec4 = {24'd0, eh[79:48], eh[47:40], eh[39:32], eh[31:0], 8'h00, 8'h45, 8'hA5};
    reg  [63:0] ln4;
    always @(posedge clk) begin
        ln4 <= rec4[64 * wi[3] +: 64];
        ob4 <= ln4[8 * wi_d[2:0] +: 8];
    end
    assign req[4] = eq_n != 5'd0;

    // ================================================================ 5 CAPTURE packets
    // served straight from diag_cap's staging register, which holds still until taken
    always @(posedge clk) pkt_take <= done[5];
    reg  [31:0]  hi1;
    reg  [255:0] lo8;
    always @* for (i6 = 0; i6 < 32; i6 = i6 + 1) begin lo8[8 * i6 +: 8] = pkt[9 * i6 +: 8]; hi1[i6] = pkt[9 * i6 + 8]; end
    wire [383:0] rec5 = (pkt_n == 16'hFFFF)
        ? {264'd0, 7'd0, tr_frames, 5'd0, tr_cause, tr_before, tr_entries, 16'hFFFF, 8'h00, 8'hC5, 8'hA5}
        : {56'd0, hi1, lo8, pkt_n, 8'h00, 8'hC5, 8'hA5};
    reg  [63:0] ln5;
    always @(posedge clk) begin
        ln5 <= rec5[64 * wi[5:3] +: 64];
        ob5 <= ln5[8 * wi_d[2:0] +: 8];
    end
    assign req[5] = pkt_ready && !pkt_take;

    // ================================================================ 6 FILL, the soak test
    reg  [15:0] f_sec; reg [9:0] f_msc; reg [7:0] f_gap; reg [11:0] f_wait; reg [15:0] f_k;
    reg  [31:0] f_ts;
    reg         r6;
    always @(posedge clk) begin
        if (rst) begin
            f_sec <= 16'd0; f_msc <= 10'd0; f_gap <= 8'd0; f_wait <= 12'd0; f_k <= 16'd0; r6 <= 1'b0; f_ts <= 32'd0;
        end else begin
            if (done[6]) begin r6 <= 1'b0; f_k <= f_k + 16'd1; f_wait <= {4'd0, f_gap} * 12'd10; end
            else if (us && f_wait != 12'd0) f_wait <= f_wait - 12'd1;
            if (k_ok && k_cmd == 8'h12) begin f_sec <= k_p01; f_msc <= 10'd0; f_gap <= k_p[39:32]; end
            else if (ms && f_sec != 16'd0) begin
                if (f_msc == 10'd999) begin f_msc <= 10'd0; f_sec <= f_sec - 16'd1; end
                else f_msc <= f_msc + 10'd1;
            end
            if (f_sec != 16'd0 && !r6 && !done[6] && f_wait == 12'd0) begin r6 <= 1'b1; f_ts <= now; end
        end
    end
    wire [127:0] h6 = {56'd0, f_k, f_ts, 8'h00, 8'h46, 8'hA5};
    reg  [63:0] ln6; reg [7:0] pat6; reg hd6;
    always @(posedge clk) begin
        ln6  <= h6[64 * wi[3] +: 64];
        pat6 <= f_k[7:0] + wi - 8'd9;
        hd6  <= wi < 8'd9;
        ob6  <= hd6 ? ln6[8 * wi_d[2:0] +: 8] : pat6;
    end
    assign req[6] = r6;

    // ================================================================ dropped records
    always @(posedge clk) lost_p <= lost0 | lost1 | lost2 | lost3 | lost4;

    // ================================================================ the writer
    // room: the FIFO takes the whole record, and below BLOCK one BLOCK more (and a margin of 4:
    // the count lags the writes by a few clocks). The dump and the soak test, which could fill
    // it, go in only while it holds less than LOW_FILL bytes, so nothing waits behind more than
    // that (3.4 ms of line).
    localparam LOW_FILL = 1024;
    wire [FIFO_AW:0] free;
    reg  [NP-1:0] room;
    always @(posedge clk) begin
        room[0] <= free >= L0 + 8'd8;
        room[1] <= free >= L1 + L0 + 8'd8;
        room[2] <= free >= L2 + L0 + 8'd8;
        room[3] <= free >= L3 + L0 + 8'd8;
        room[4] <= free >= L4 + L0 + 8'd8;
        room[5] <= free >= (1 << FIFO_AW) - LOW_FILL + L5;
        room[6] <= free >= (1 << FIFO_AW) - LOW_FILL + L6;
    end
    localparam [1:0] W_IDLE = 2'd0, W_COPY = 2'd1, W_GAP = 2'd2;
    reg  [1:0]    wst;
    reg  [NP-1:0] sel_q;
    reg  [NP-1:0] first;
    reg  [7:0]    wl, wi_d2, pos_a, len_a;
    reg           cp_d, cp_d2;              // wi was served two clocks ago: its byte is in ob_k now
    reg  [7:0]    wb;
    reg           va;
    reg  [7:0]    seq, xacc;
    reg           f_we;
    reg  [7:0]    f_wd;
    reg  [1:0]    gap;
    wire [NP-1:0] ready = req & room & ~done & ~sel_q;
    always @* begin
        first = {NP{1'b0}};
        for (i7 = NP - 1; i7 >= 0; i7 = i7 - 1) if (ready[i7]) first = {{(NP-1){1'b0}}, 1'b1} << i7;
    end
    reg  [7:0] mux;
    always @* begin
        mux = 8'd0;
        if (sel_q[0]) mux = mux | ob0;
        if (sel_q[1]) mux = mux | ob1;
        if (sel_q[2]) mux = mux | ob2;
        if (sel_q[3]) mux = mux | ob3;
        if (sel_q[4]) mux = mux | ob4;
        if (sel_q[5]) mux = mux | ob5;
        if (sel_q[6]) mux = mux | ob6;
    end
    always @(posedge clk) begin
        done <= {NP{1'b0}};
        if (rst) begin
            wst <= W_IDLE; sel_q <= {NP{1'b0}}; wi <= 8'd0; wi1 <= 8'd0; wl <= 8'd0; wi_d <= 8'd0; wi_d2 <= 8'd0; cp_d <= 1'b0;
            cp_d2 <= 1'b0; wb <= 8'd0;
            pos_a <= 8'd0; len_a <= 8'd0; va <= 1'b0; seq <= 8'd0; xacc <= 8'd0; f_we <= 1'b0; f_wd <= 8'd0; gap <= 2'd0;
        end else begin
            // the index: the producers serve byte wi two clocks later
            cp_d <= 1'b0; cp_d2 <= cp_d; wi_d <= wi; wi_d2 <= wi_d;
            case (wst)
            // wi is 0 here already (reset, or the gap's end): the pick does not reach wi's 16
            // registers (pick -> wi was a slowest path, 2026-10-04)
            W_IDLE: if (first != {NP{1'b0}}) begin
                sel_q <= first; wst <= W_COPY;
                wl <= first[0] ? L0 : first[1] ? L1 : first[2] ? L2 : first[3] ? L3 : first[4] ? L4 : first[5] ? L5 : L6;
            end
            W_COPY: begin
                cp_d <= 1'b1;
                if (wi == wl - 8'd1) begin wst <= W_GAP; gap <= 2'd3; end
                else begin wi <= wi + 8'd1; wi1 <= wi1 + 8'd1; end
            end
            W_GAP: begin
                if (gap == 2'd1) begin wst <= W_IDLE; sel_q <= {NP{1'b0}}; wi <= 8'd0; wi1 <= 8'd0; end
                gap <= gap - 2'd1;
            end
            default: wst <= W_IDLE;
            endcase
            // stage A: the producer's byte
            va <= cp_d2;
            if (cp_d2) begin
                wb <= mux; pos_a <= wi_d2; len_a <= wl;
                if (wi_d2 == wl - 8'd1) done <= sel_q;
            end
            // stage B: the sequence number at byte 2, the XOR last
            f_we <= va;
            if (va) begin
                if (pos_a == len_a - 8'd1) begin
                    f_wd <= xacc; xacc <= 8'd0; seq <= seq + 8'd1;
                end else if (pos_a == 8'd2) begin
                    f_wd <= seq; xacc <= xacc ^ seq;
                end else begin
                    f_wd <= wb; xacc <= xacc ^ wb;
                end
            end
        end
    end

    // ================================================================ FIFO and line
    wire       f_av, f_take; wire [7:0] f_q;
    diag_fifo #(.AW(FIFO_AW)) u_fifo (.clk(clk), .rst(rst), .we(f_we), .wd(f_wd), .free(free),
                                      .avail(f_av), .q(f_q), .take(f_take));
    diag_uart_tx #(.DIV(DIV), .STOP(STOP)) u_tx (.clk(clk), .rst(rst), .avail(f_av), .data(f_q),
                                                 .take(f_take), .txd(txd));
endmodule
