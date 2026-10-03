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
    output reg         run,                     // the train is pinned to the ring and running
    output reg         tick,                    // a tick in this clock
    output reg  [2:0]  sub,                     // ...at this sample of its 8
    output reg  [9:0]  phase_n,                 // the phase after this tick: 0 is the frame start
    output reg  [31:0] per,                     // Q8.24 samples a tick
    output reg         per_ok,                  // per is measured, not the nominal
    output reg         rate48,                  // under 17 samples a tick: 48 kHz (else 44.1)
    output reg  [31:0] err_last                 // the last phase error seen, samples (signed), for the bench
);
    localparam [9:0] PH_UI0 = (1024 - D_TICKS) % 1024;   // the phase at a frame's UI 0

    // ---------------------------------------------------------------- the train
    wire [31:0] now  = {wc, 3'b000};
    reg  [31:0] nt_i;                           // the next tick: its sample time...
    reg  [23:0] nt_f;                           // ...and fraction
    reg  [9:0]  phase;                          // the phase of the last tick
    reg  [31:0] t_ui0;                          // the time of the last tick at PH_UI0
    reg         armed;                          // pinned, waiting for the frame start to run
    wire [31:0] ahead = nt_i - now;             // the next tick's distance from this word's first sample
    wire        due  = $signed(ahead) < 32'sd8; // it falls in this word (or is overdue)
    wire [2:0]  pos  = ahead[31] ? 3'd0 : ahead[2:0];
    wire [55:0] nt   = {nt_i, nt_f};
    wire [55:0] nt_adv = nt + {24'd0, per};     // one tick on
    // the phase error at a frame edge, against the last tick at PH_UI0, wrapped into a frame
    wire [31:0] per_i   = per >> 14;            // the frame period, samples (1024 ticks)
    wire [31:0] half_p  = per_i >> 1;
    wire [31:0] e_raw   = fe_t - t_ui0;
    wire [31:0] e_wrap  = ($signed(e_raw) > $signed(half_p)) ? e_raw - per_i :
                          ($signed(e_raw) < -$signed(half_p)) ? e_raw + per_i : e_raw;
    // the correction, e / 2^KP_LOG2, with its fraction (Q.24): taken to whole samples it left
    // a dead zone of 2^KP_LOG2 samples the offset could sit anywhere in
    wire [55:0] corr    = $signed({e_wrap, 24'd0}) >>> KP_LOG2;
    wire        far     = $signed(e_wrap) > 32'sd128 || $signed(e_wrap) < -32'sd128;    // not tracking: pin anew
    wire        near    = $signed(e_wrap) <= 32'sd4 && $signed(e_wrap) >= -32'sd4;      // tracking: the loop's
                                                // step is then a quarter sample, the first frame out is clean
    wire        ui0_ev  = fe_valid && fe_rise && locked;
    reg  [1:0]  good;                           // edges in a row with a small error, saturating at 2

    // ---------------------------------------------------------------- the period
    // Over the last 2^m frames, m growing with the frames seen since the lock up to AVG_LOG2:
    // from the second frame on the period is the ring's to one sample in two frames (60 ppm),
    // from the 64th to 20 ps a tick. The nominal counts only until then.
    reg  [31:0] hist [0:(1 << AVG_LOG2) - 1];   // the last 2^AVG_LOG2 frame starts
    reg  [AVG_LOG2 - 1:0] hidx;
    reg  [7:0]  nhist;                          // frame starts since the lock, saturating
    wire [2:0]  m = nhist >= 8'd64 ? 3'd6 : nhist >= 8'd32 ? 3'd5 : nhist >= 8'd16 ? 3'd4 :
                    nhist >= 8'd8 ? 3'd3 : nhist >= 8'd4 ? 3'd2 : nhist >= 8'd2 ? 3'd1 : 3'd0;
    wire [AVG_LOG2 - 1:0] back = hidx - (1 << m);
    wire [31:0] span    = fe_t - hist[back];    // 2^m frames of ring time
    wire [31:0] per_new = span << (14 - m);     // span / (2^m x 1024) in Q8.24
    wire        per_sane = m != 3'd0 && per_new[31:24] >= 8'd15 && per_new[31:24] <= 8'd18;

    integer k;
    initial for (k = 0; k < (1 << AVG_LOG2); k = k + 1) hist[k] = 32'd0;

    always @(posedge clk) begin
        tick <= 1'b0;
        if (rst) begin
            run <= 1'b0; armed <= 1'b0; good <= 2'd0; sub <= 3'd0; phase_n <= 10'd0; phase <= 10'd0;
            nt_i <= now + 32'd16; nt_f <= 24'd0; t_ui0 <= 32'd0;
            per <= PER_NOM; per_ok <= 1'b0; rate48 <= 1'b1; err_last <= 32'd0;
            hidx <= {AVG_LOG2{1'b0}}; nhist <= 8'd0;
        end else begin
            // the train, every clock
            if (due) begin
                tick    <= 1'b1;
                sub     <= pos;
                phase   <= phase + 10'd1;
                phase_n <= phase + 10'd1;
                {nt_i, nt_f} <= nt_adv;
                if (phase + 10'd1 == PH_UI0) t_ui0 <= nt_i;
                // run from a frame start, once the train has tracked two edges with the period measured
                if (phase + 10'd1 == 10'd0 && armed && good == 2'd2) run <= 1'b1;
            end
            // the ring's frame starts
            if (!locked) begin
                run <= 1'b0; armed <= 1'b0; good <= 2'd0; nhist <= 8'd0;
            end else if (ui0_ev) begin
                if (!armed || far) begin
                    // pin (or pin anew, the train being far off): UI 0 is phase PH_UI0, the
                    // next tick one period on; the output stops until the train tracks again
                    phase <= PH_UI0;
                    t_ui0 <= fe_t;
                    {nt_i, nt_f} <= {fe_t, 24'd0} + {24'd0, per};
                    armed <= 1'b1;
                    good <= 2'd0;
                    run <= 1'b0;
                    err_last <= armed ? e_wrap : 32'd0;
                end else begin
                    {nt_i, nt_f} <= (due ? nt_adv : nt) + corr;
                    err_last <= e_wrap;
                    if (near && m != 3'd0) begin
                        if (good != 2'd2) good <= good + 2'd1;
                    end else good <= 2'd0;
                end
                // the period over the last 2^m frames; a pin starts the history anew, so a
                // jump of the ring's timing never sits inside a span (it would be read as a
                // period error for 2^AVG_LOG2 frames and the train could not track)
                hist[hidx] <= fe_t;
                hidx <= hidx + 1'b1;
                if (!armed || far) begin
                    nhist <= 8'd1;
                end else begin
                    if (nhist != 8'hFF) nhist <= nhist + 8'd1;
                    if (per_sane) begin
                        per <= per_new;
                        per_ok <= m == AVG_LOG2;
                        rate48 <= per_new[31:24] < 8'd17;
                    end
                end
            end
        end
    end
endmodule
