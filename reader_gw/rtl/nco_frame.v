// nco_frame.v - the ring's frame rate as a tick train on the receiver's own clock.
//
// The reader has one clock, the receiver's 99 MHz (clk_s); nothing follows the ring but this
// train: 1024 ticks a frame, the time base amp_out's engine starts on and spdif_tx draws its
// half-cells from (phase_n, as tdm_out gave it in MOST25-to-AUDIO). Each tick is placed to one
// sample of the receiver's 792 Msps grid (1.26 ns), so an edge drawn from it through OSER8 sits
// on that grid too - not on the 10.1 ns clock grid.
//
// Period: the mean over the last 2^m frames of the receiver's frame starts (fe_t of UI 0, the
// same 1.26 ns time base), m growing with the frames seen up to AVG_LOG2, as a Q8.24 number of
// samples a tick: with 64 frames that is 20 ps a tick, 20 ps over a frame - the ring's own
// jitter is far more. The nominal 48 kHz period (JLR's rate) counts for the first frame only;
// a measurement outside 15..18 samples a tick (not a MOST25 frame rate) is not taken.
// Phase: the frame's UI 0 falls at phase 1024 - D_TICKS, so the train's frame start (phase 0)
// comes D_TICKS after it: 128 ticks, 2.6 us, after the frame before has completed, when its
// bytes are long collected. On the first frame edge after a lock the train is pinned there;
// after that, each edge's error against the tick of that phase is taken out by 1/2^KP_LOG2 -
// the period is right from the measurement, the error only drifts, so a weak loop holds it
// and smooths the edges' jitter. An error over 128 samples means the train is not tracking
// (the ring jumped): it is pinned anew rather than slewed for dozens of frames, and the
// period's history starts anew with it, so the jump never sits inside a span. The train runs
// (run) from a frame start once two edges in a row were within 4 samples with the period
// measured (the loop's step is then a quarter sample: the first frame out is as clean as the
// rest), and stops when the receiver unlocks or the train is pinned anew: what leaves is never
// a frame with a jump in it.
//
// Timing. Taken in the edge's own clock, the error (subtract, wrap, compares, the correction
// into the 56-bit train) and the period (history index, read, subtract, shift, range check)
// were 16 ns of clk_s's 10.1. An edge comes once a frame (2062 clocks), so its result now
// lands three clocks later (E = the clock fe_valid is high). The receiver knows a UI 0's time
// a clock before it brings it (fe_next, its prev_q, in the clock its ev_start is high), so the
// two subtracts that would start clock E start in E-1:
//   E-1   the period, from fe_next and the history entry read ahead of time - the index and the
//         entry only change when an edge lands - range-checked; the error's subtract from
//         fe_next, against t_ui0 and against nt_i in case the PH_UI0 tick is in this clock
//         (t_ui0 takes nt_i at its end)
//   E     the period taken into the train's own period per_t when it is sane, so the train
//         runs on it from E+1 as before; the error's compares against half a frame and both
//         of its wrapped values
//   E+1   the error wrapped into a frame
//   E+2   far / near, the pin's next tick, the correction plus one period
//   E+3   it lands: the correction added to the train as it stands then (it kept ticking), or
//         the pin; per, per_ok, rate48, err_last, the counts and the history
// Everything the edge measures is measured in clock E from the same registers as before, so
// every number is the one the one-clock code got. The correction is relative and the train's
// period changed at E as before, so from E+3 on every tick's time (its phase and its sample)
// is exactly the one-clock code's. Only the ticks put out in E+1..E+3 sit where the train had
// them, without this edge's correction (a quarter sample while tracking); and the next one,
// should the correction move it back into a clock already gone, comes at the first sample of
// the next clock, between where it was and where the correction put it. A pin is absolute
// (fe_t + per). Should the edge pin, the period taken at E is put back with it (the one-clock
// code took none on a pin).
// What the early work and the train's register q (below) rely on, both given by rx_framer and
// reader_core: fe_next in E-1 is fe_t of E (the receiver's prev_q), frame starts come at least
// 9 clocks apart (a frame, 2000 clocks, on the ring), and wc is 0 in rst's last clock and
// counts one a clock after it. q is the train's time to its next tick held beside nt; it is
// set anew at every pin, and nothing else re-derives it.
module nco_frame #(
    parameter [31:0] PER_NOM = 32'd270336000,   // 16500 / 1024 samples (48 kHz at 792 Msps), Q8.24
    parameter AVG_LOG2 = 6,                     // the period: the mean over 2^AVG_LOG2 frames
    parameter D_TICKS  = 128,                   // ticks from UI 0 to the train's frame start
    parameter KP_LOG2  = 4                      // the phase error's share taken out per frame: 1/16
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [28:0] wc,                      // the receiver's word counter: time = wc x 8 samples
    input  wire        locked,                  // rx_framer locked
    input  wire        fe_valid,                // a frame edge seen (rx_framer)
    input  wire        fe_rise,                 // ...UI 0 (else UI 512, not used here)
    input  wire [31:0] fe_t,                    // its sample time
    input  wire [31:0] fe_next,                 // a UI 0's time a clock before fe_valid brings it (E-1)
    output reg         run,                    // the train is pinned to the ring and running
    output reg         tick,                    // a tick in this clock
    output reg         fstart,                  // ...and it is the frame start's: tick && phase_n == 0
    output reg  [2:0]  sub,                     // ...at this sample of its 8
    output reg  [9:0]  phase_n,                 // the phase after this tick: 0 is the frame start
    output reg  [31:0] per,                     // Q8.24 samples a tick
    output reg         per_ok,                  // per is measured, not the nominal
    output reg         rate48,                  // under 17 samples a tick: 48 kHz (else 44.1)
    output reg  [31:0] err_last,                // the last phase error seen, samples (signed), for the bench
    output wire        pin_o                    // pulse: a landing pins the train anew (the log)
);
    localparam [9:0] PH_UI0 = (1024 - D_TICKS) % 1024;   // the phase at a frame's UI 0
    localparam [9:0] PH_PRE = PH_UI0 - 10'd1;            // the phase whose next tick is PH_UI0's

    wire        ui0_ev = fe_valid && fe_rise && locked;  // a frame start, the receiver locked (clock E)

    // ---------------------------------------------------------------- the train's registers
    wire [31:0] now  = {wc, 3'b000};
    reg  [31:0] nt_i;                           // the next tick: its sample time...
    reg  [23:0] nt_f;                           // ...and fraction
    reg  [31:0] per_t;                          // the train's period: per, but from the edge's clock on
    reg  [9:0]  phase;                          // the phase of the last tick
    reg  [31:0] t_ui0;                          // the time of the last tick at PH_UI0...
    reg  [23:0] tf;                             // ...and its fraction (for uf)
    reg         uf;                             // that tick came while an edge was in flight: it lacks the correction
    reg         armed;                          // pinned, waiting for the frame start to run
    reg  [1:0]  good;                           // edges in a row with a small error, saturating at 2

    // ---------------------------------------------------------------- an edge in flight
    reg         v1, v2, v3;                     // its result is 1, 2, 3 clocks on (v3: it lands in this clock)
    reg  [31:0] fe_q;                           // its time
    reg         arm_e;                          // armed at the edge
    reg  [31:0] e_raw_q;                        // its error against the last tick at PH_UI0 (E)
    reg  [31:0] e_wrap_q;                       // ...wrapped into a frame (E+1)
    reg         pin_q, near_q;                  // it pins anew / tracks, with the period measured (E+2)
    assign pin_o = v3 && pin_q;
    reg  [55:0] add_op;                         // what add_t adds in the next clock: one period, plus the
                                                // correction in the landing clock
    reg  [55:0] addn_op;                        // what add_n adds in the next clock: the correction, or 0
    reg  [55:0] pin_nt;                         // the pin's next tick, fe_t + per
    reg  [31:0] pn_e;                           // the period it measured...
    reg         ps_e, r48_e, pok_e, mnz_e;      // ...sane, under 17, over the full history; m != 0

    // ---------------------------------------------------------------- the period's history
    // Over the last 2^m frames, m growing with the frames seen since the lock up to AVG_LOG2:
    // from the second frame on the period is the ring's to one sample in two frames (60 ppm),
    // from the 64th to 20 ps a tick. The nominal counts only until then.
    reg  [31:0] hist [0:(1 << AVG_LOG2) - 1];   // the last 2^AVG_LOG2 frame starts
    reg  [AVG_LOG2 - 1:0] hidx;
    reg  [7:0]  nhist;                          // frame starts since the lock, saturating
    wire [2:0]  m = nhist >= 8'd64 ? 3'd6 : nhist >= 8'd32 ? 3'd5 : nhist >= 8'd16 ? 3'd4 :
                    nhist >= 8'd8 ? 3'd3 : nhist >= 8'd4 ? 3'd2 : nhist >= 8'd2 ? 3'd1 : 3'd0;
    // The entry 2^m frames back and the bound of the range check, read ahead of time: hidx,
    // nhist and hist change only when an edge lands, 2000 clocks before the next one needs them
    // (these settle in 4). A lost lock clears nhist at any clock, but armed with it, and an edge
    // that finds armed clear pins and takes no period. The index is modulo the history's length
    // (it was hidx - (1 << m), a 32-bit expression cut to AVG_LOG2 bits by the synthesizer,
    // warning EX3791: harmless, the low bits of a difference are the difference of the low bits;
    // written out here): 2^AVG_LOG2 is 0, back = hidx, the oldest entry, which this edge replaces.
    reg  [2:0]  m_q /* synthesis syn_maxfan = 16 */;   // selects the shift of two 32-bit periods: copied, not one net to all
    reg  [10:0] msk_q;                          // bits 12+m..17+m of dlo (as dlo[23:13]): zero when sane
    reg  [AVG_LOG2 - 1:0] back_q;
    reg  [31:0] hb_q;                           // hist[back]: the frame start 2^m frames back
    reg  [31:0] hb_r;                           // ...once more, off the history's memory: a flip-flop
                                                // in front of the period's subtract, not the RAM's output
    reg  [31:0] lo_q;                           // hb_q + 15 << (10 + m): the span of 15 samples a tick
    reg  [31:0] hbk_q;                          // hb_q + 2^(13 + m): the span less 8 samples a tick
    wire [AVG_LOG2:0] two_m = {{AVG_LOG2{1'b0}}, 1'b1} << m_q;
    always @(posedge clk) begin
        m_q    <= m;
        msk_q  <= (m == 3'd0) ? 11'd0 : (11'h03F << (m - 3'd1));
        back_q <= hidx - two_m[AVG_LOG2 - 1:0];
        hb_q   <= hist[back_q];
        hb_r   <= hb_q;
        lo_q   <= hb_q + (32'd15 << (5'd10 + m_q));
        hbk_q  <= hb_q + (32'd1 << (5'd13 + m_q));
    end

    // The period, worked out in E-1 from fe_next (= fe_t of clock E) and taken in E. per_new =
    // span << (14 - m), cut to 32 bits, so its integer part is span[17+m:10+m]; it is 15..18
    // exactly when span - 15 x 2^(10+m) is under 4 x 2^(10+m) modulo 2^(18+m), i.e. when bits
    // 12+m..17+m of fe_t - lo_q are zero, and under 17 when bit 11+m is zero as well: one
    // subtract and a masked zero test, not a shift and two compares after the subtract.
    // m_q, msk_q, hb_q and lo_q are the same in E-1 as in E: they follow nhist and hidx, which
    // change when an edge lands (2000 clocks before the next; these settle in 5) or when the lock is lost - and
    // then armed falls with them, the edge pins and nothing it measured is taken.
    wire [31:0] span = fe_next - hb_r;          // 2^m frames of ring time
    wire [31:0] dlo  = fe_next - lo_q;
    reg  [31:0] pn_f;                           // span / (2^m x 1024) in Q8.24
    reg         r48_f;
    always @* begin
        case (m_q)
            3'd1:    begin pn_f = span << 13; r48_f = ~dlo[12]; end
            3'd2:    begin pn_f = span << 12; r48_f = ~dlo[13]; end
            3'd3:    begin pn_f = span << 11; r48_f = ~dlo[14]; end
            3'd4:    begin pn_f = span << 10; r48_f = ~dlo[15]; end
            3'd5:    begin pn_f = span << 9;  r48_f = ~dlo[16]; end
            3'd6:    begin pn_f = span << 8;  r48_f = ~dlo[17]; end
            default: begin pn_f = span << 14; r48_f = 1'b0;     end   // m = 0: never taken
        endcase
    end
    wire        ps_f = m_q != 3'd0 && (dlo[23:13] & msk_q) == 11'd0;
    // the same less 8 samples a tick (2^27 in Q8.24), for q's operand: pn_f - 2^27 is
    // (span - 2^(27-k)) << k with k = 14 - m; equal to pn_f - 2^27 whenever pn_f is sane (the only
    // time it is taken)
    wire [31:0] spanm = fe_next - hbk_q;
    reg  [31:0] pn_fm;
    always @* begin
        case (m_q)
            3'd1:    pn_fm = spanm << 13;
            3'd2:    pn_fm = spanm << 12;
            3'd3:    pn_fm = spanm << 11;
            3'd4:    pn_fm = spanm << 10;
            3'd5:    pn_fm = spanm << 9;
            3'd6:    pn_fm = spanm << 8;
            default: pn_fm = spanm << 14;
        endcase
    end
    reg  [31:0] pn_r;                           // the period, the clock before E (only E reads them)
    reg  [31:0] pn_rm;                          // ...less 8 samples a tick
    reg         ps_r, r48_r, pok_r, mnz_r;
    always @(posedge clk) begin
        pn_r  <= pn_f;
        pn_rm <= pn_fm;
        ps_r  <= ps_f;
        r48_r <= r48_f;
        pok_r <= m_q == AVG_LOG2;
        mnz_r <= m_q != 3'd0;
    end

    // ---------------------------------------------------------------- the error, E+1 and E+2
    // the phase error at a frame edge, against the last tick at PH_UI0, wrapped into a frame;
    // per changes only when an edge lands, so per, half_p and its negative (a register: the
    // compare without a negation in front of it) are the values of clock E
    wire [31:0] per_i   = per >> 14;            // the frame period, samples (1024 ticks)
    wire [31:0] half_p  = per_i >> 1;
    reg  [31:0] nhp_q;                          // -half_p
    // E-1: fe_next against the last tick at PH_UI0 as it will stand in E. t_ui0 changes at the
    // end of E-1 only if the PH_UI0 tick is in E-1 (it then takes nt_i): an edge's result
    // lands 3 clocks after it, and the next frame start is a frame later.
    reg  [31:0] e0_q, e1_q;                     // fe_next - t_ui0, fe_next - nt_i
    reg         e1_s;                           // the PH_UI0 tick was in that clock: e1_q is the one
    wire        pre  = phase == PH_PRE;         // the next tick is PH_UI0's
    // E: the error and, from it, its compares against half a frame and both wrapped values
    wire [31:0] e_raw = e1_s ? e1_q : e0_q;     // fe_t - t_ui0
    reg         gt_q, lt_q;
    reg  [31:0] em_q, ep_q;
    wire [31:0] e_wrap  = gt_q ? em_q : lt_q ? ep_q : e_raw_q;
    // the correction, e / 2^KP_LOG2, with its fraction (Q.24): taken to whole samples it left
    // a dead zone of 2^KP_LOG2 samples the offset could sit anywhere in
    wire [55:0] corr_q  = $signed({e_wrap_q, 24'd0}) >>> KP_LOG2;
    wire        far     = $signed(e_wrap_q) > 32'sd128 || $signed(e_wrap_q) < -32'sd128;   // not tracking: pin anew
    wire        near    = $signed(e_wrap_q) <= 32'sd4 && $signed(e_wrap_q) >= -32'sd4;     // tracking: the loop's
                                                // step is then a quarter sample, the first frame out is clean

    always @(posedge clk) begin
        nhp_q <= 32'd0 - half_p;
        v1 <= ui0_ev && !rst;
        v2 <= v1 && !rst;
        v3 <= v2 && !rst;
        if (ui0_ev) begin                       // E
            fe_q    <= fe_t;
            e_raw_q <= e_raw;
            gt_q    <= $signed(e_raw) > $signed(half_p);
            lt_q    <= $signed(e_raw) < $signed(nhp_q);
            em_q    <= e_raw - per_i;
            ep_q    <= e_raw + per_i;
            arm_e   <= armed;
            pn_e    <= pn_r;
            ps_e    <= ps_r;
            r48_e   <= r48_r;
            pok_e   <= pok_r;
            mnz_e   <= mnz_r;
        end
        if (v1) e_wrap_q <= e_wrap;             // E+1
        if (v2) begin                           // E+2
            pin_q  <= !arm_e || far;
            near_q <= near && mnz_e;
            pin_nt <= {fe_q, 24'd0} + {24'd0, per};
        end
    end

    // ---------------------------------------------------------------- the train
    // due: the next tick falls in this word (or is overdue), nt_i - now < 8 signed. now's low
    // three bits are zero, so that is the word part alone: nt_i[31:3] - wc negative, or zero
    // (then nt_i[31:3] - wc - 1 is negative). Two carry chains side by side and an OR - a
    // subtract, then a compare over its 32 bits, was the train's own long path.
    // That compare is no longer made: q = nt_i - now - 8, kept as a register of its own beside
    // nt and moved by the same sums (less the 8 samples of a clock), is the time from the next
    // clock's start to the next tick, so due (nt_i - now < 8) is q's sign bit. With nt_f as its
    // fraction q is exact. The tick's sample in its word is q's low bits (now and 8 are whole
    // words), 0 when the tick is overdue (q < -8). q's reset value assumes wc is cleared by the
    // same rst, as reader_core's is.
    reg  [31:0] q_i;
    wire        due  = q_i[31];
    wire [2:0]  pos  = (&q_i[31:3]) ? q_i[2:0] : 3'd0;
    // The next tick's two candidates, the choice made by due alone: one period on, or none;
    // in the landing clock the correction rides along. The operands are registers set up the
    // clock before (v3 follows v2, per_t's next value is known), so no select sits in front of
    // the 56-bit chains.
    wire [55:0] nt     = {nt_i, nt_f};
    wire [55:0] add_t  = nt + add_op;
    wire [55:0] add_n  = nt + addn_op;
    // per_t as it will stand in the next clock (the train block below sets it so)
    // take: the edge's period goes into the train (clock E). It comes off the receiver late, so
    // it is the last choice of each register it sets; E is never a landing clock (v2, v3: an
    // edge's result lands 3 clocks after it, the next frame start is a frame later), so the
    // order of the choices does not matter.
    wire        take = ui0_ev && armed && ps_r;
    wire [55:0] add_nt  = v2 ? {24'd0, per_t} + corr_q : (v3 && pin_q) ? {24'd0, per} : {24'd0, per_t};
    wire [55:0] add_nx  = take ? {24'd0, pn_r} : add_nt;   // v2: the landing is next
    wire [55:0] addn_nx = v2 ? corr_q : 56'd0;
    // q's operands are add_op and addn_op less a clock's 8 samples (2^27 in Q8.24). Taken off
    // after the select it was a subtract behind the edge's enable; so per_t less 8 samples is a
    // register of its own (ptm8), set wherever per_t is, from values kept less 8 already.
    localparam [55:0] C8 = {32'd8, 24'd0};
    reg  [55:0] add_opm, addn_opm;              // the same, less a clock's 8 samples: q's operands
    reg  [55:0] ptm8, per_m8;                   // per_t, per less 8 samples
    wire [55:0] ptm8_nt = (v3 && pin_q) ? per_m8 : ptm8;
    wire [55:0] ptm8_nx = take ? {24'd0, pn_rm} : ptm8_nt;
    reg  [31:0] pin_a, perm32;                  // a pin's q in two steps: fe_q - now (E+1), per - 32
    reg  [31:0] pin_qi;                         // q after a pin (E+2 for E+3): fe_t + per - now(E+4) - 8
    always @(posedge clk) begin
        per_m8 <= {24'd0, per} - C8;
        perm32 <= {24'd0, per[31:24]} - 32'd32;
        if (rst) begin
            add_op   <= {24'd0, PER_NOM};
            addn_op  <= 56'd0;
            ptm8     <= {24'd0, PER_NOM} - C8;
            add_opm  <= {24'd0, PER_NOM} - C8;
            addn_opm <= 56'd0 - C8;
        end else begin
            add_op   <= add_nx;
            addn_op  <= addn_nx;
            ptm8     <= ptm8_nx;
            add_opm  <= take ? {24'd0, pn_rm} : v2 ? ptm8 + corr_q : ptm8_nt;
            addn_opm <= v2 ? corr_q - C8 : 56'd0 - C8;
        end
        // pin_nt's whole samples (fe_q + per's integer part; fe_q has no fraction to carry) less
        // now(E+3) + 16: fe_q - now(E+1) + per's integer part - 32
        if (v1) pin_a <= fe_q - now;
        if (v2) pin_qi <= pin_a + perm32;
    end
    wire [55:0] qa = {q_i, nt_f} + add_opm;     // a tick
    wire [55:0] qb = {q_i, nt_f} + addn_opm;    // none (the landing's correction, or nothing)
    wire [31:0] q_due   = (v3 && pin_q) ? pin_qi : qa[55:24];
    wire [31:0] q_nodue = (v3 && pin_q) ? pin_qi : qb[55:24];
    // the next tick, with due as the last choice: a tick moves it on, a landing corrects it or
    // pins it (the pin wins over a tick in the same clock)
    wire [55:0] nt_due   = (v3 && pin_q) ? pin_nt : add_t;
    wire [55:0] nt_nodue = v3 ? (pin_q ? pin_nt : add_n) : nt;
    // the tick at PH_UI0 that came while the edge was in flight, as the one-clock code had it
    wire [55:0] tfix   = {t_ui0, tf} + corr_q;

    // E-1 for the error (every clock; E reads the pair of the clock before it)
    always @(posedge clk) begin
        e0_q <= fe_next - t_ui0;
        e1_q <= fe_next - nt_i;
        e1_s <= due && pre;
    end

    // What t_ui0, tf and uf take, with due as the last choice: due comes off two carry chains
    // late in the clock, the rest are registers and the landing's sums. As before: the PH_UI0
    // tick (due && pre) takes the tick's time, a landing takes the pin's time or, the PH_UI0
    // tick being in the same clock, its time with the correction, or the correction for a
    // PH_UI0 tick that came while the edge was in flight (uf); the landing clears uf.
    wire [31:0] t_land  = pin_q ? fe_q : uf ? tfix[55:24] : t_ui0;     // v3, no PH_UI0 tick
    wire [31:0] t_nodue = v3 ? t_land : t_ui0;
    wire [31:0] t_due   = !pre ? t_nodue : !v3 ? nt_i : pin_q ? fe_q : add_n[55:24];
    wire        uf_nodue = !v3 && uf;
    wire        uf_due   = !v3 && (uf || (pre && (v1 || v2)));

    integer k;
    initial for (k = 0; k < (1 << AVG_LOG2); k = k + 1) hist[k] = 32'd0;

    always @(posedge clk) begin
        tick <= 1'b0;
        fstart <= 1'b0;
        if (rst) begin
            run <= 1'b0; armed <= 1'b0; good <= 2'd0; sub <= 3'd0; phase_n <= 10'd0; phase <= 10'd0;
            // the first tick two words after reset; wc is cleared by the same rst (reader_core's
            // is), so now is 0 from the next clock on and these are nt_i = now + 16 and
            // q = nt_i - now - 8 there - constants, not a sum on the word counter. (The sum gave
            // now + 16 of rst's last clock; the two agree when rst lasts 2 clocks or more, as it
            // always does here: the board's lasts 65537, the testbenches' 4 and 20.)
            nt_i <= 32'd16; nt_f <= 24'd0; t_ui0 <= 32'd0; tf <= 24'd0; uf <= 1'b0;
            q_i <= 32'd8;
            per <= PER_NOM; per_t <= PER_NOM; per_ok <= 1'b0; rate48 <= 1'b1; err_last <= 32'd0;
            hidx <= {AVG_LOG2{1'b0}}; nhist <= 8'd0;
        end else begin
            // the train, every clock
            if (due) begin
                tick    <= 1'b1;
                fstart  <= phase == 10'd1023;
                sub     <= pos;
                phase   <= phase + 10'd1;
                phase_n <= phase + 10'd1;
                // run from a frame start, once the train has tracked two edges with the period
                // measured. A frame start while an edge is in flight means the train is ~1900
                // samples off that edge (D_TICKS ticks from UI 0): the edge pins, and the
                // one-clock code had stopped the train at it - so stop here, never start.
                if (phase == 10'd1023) begin
                    if (ui0_ev || v1 || v2 || v3) run <= 1'b0;
                    else if (armed && good == 2'd2) run <= 1'b1;
                end
            end
            {nt_i, nt_f} <= due ? nt_due : nt_nodue;
            q_i <= due ? q_due : q_nodue;
            // the last tick at PH_UI0 and whether it lacks a correction (see t_due above)
            t_ui0 <= due ? t_due : t_nodue;
            if (due && pre) tf <= nt_f;
            uf <= due ? uf_due : uf_nodue;
            // the period the edge measured, into the train from the next clock on, as the
            // one-clock code did; put back below if the edge turns out to pin
            if (take) per_t <= pn_r;
            // the edge's result lands (E+3)
            if (v3) begin
                if (pin_q) begin
                    // pin (or pin anew, the train being far off): UI 0 is phase PH_UI0, the
                    // next tick one period on; the output stops until the train tracks again
                    phase <= PH_UI0;
                    armed <= 1'b1;
                    good <= 2'd0;
                    run <= 1'b0;
                    err_last <= arm_e ? e_wrap_q : 32'd0;
                    per_t <= per;
                    nhist <= 8'd1;
                end else begin
                    err_last <= e_wrap_q;
                    if (near_q) begin
                        if (good != 2'd2) good <= good + 2'd1;
                    end else good <= 2'd0;
                    if (nhist != 8'hFF) nhist <= nhist + 8'd1;
                    if (ps_e) begin
                        per <= pn_e;
                        per_ok <= pok_e;
                        rate48 <= r48_e;
                    end
                end
                // the period over the last 2^m frames; a pin starts the history anew, so a
                // jump of the ring's timing never sits inside a span (it would be read as a
                // period error for 2^AVG_LOG2 frames and the train could not track)
                hist[hidx] <= fe_q;
                hidx <= hidx + 1'b1;
            end
            // a lost lock, at any clock; an edge taken before it still lands (the one-clock
            // code had taken it whole), but stopped, unarmed, its counts cleared
            if (!locked) begin
                run <= 1'b0; armed <= 1'b0; good <= 2'd0; nhist <= 8'd0;
            end
        end
    end
endmodule
