// rx_classify.v - run length in samples -> 1, 2 or 3 UI.
//
// Two quantities are learned from the line itself, so neither the ring rate
// (44.1 or 48 kHz) nor the receiver's pulse-width distortion has to be known:
//
//   ui  - one UI in samples, Q8.8.  Starts at 17.0, between 16.1 (48 kHz) and
//         17.5 (44.1 kHz); both classify correctly from the first run.
//   b   - pulse-width bias, Q8.8 signed. MOST SP4 lets a HIGH pulse be up to
//         +0.40 / -0.257 UI off and a LOW pulse the mirror of that; a single
//         1.5 UI threshold then leaves no margin. HIGH runs are corrected by
//         -b, LOW runs by +b, which is how the spec's own model (a falling
//         edge that moves) behaves.
//
// After correction a run r is class 1 below 1.5 UI, 2 below 2.5, 3 below 3.5;
// anything else is class 0 (error). Only classes 1 and 2 train the loops:
// class 3 appears once or twice a frame and adds nothing.
//
// Every run also leaves with its length in whole UI (sym_len), for the
// regenerator: for classes 1..3 that is the class; an error run carries its
// rounded length, 0 (below half a UI) to 15 (15.5 UI and above). The line
// goes out as it came in, errors included; the framer, not the regenerator,
// judges them.
//
// A word of the sampler that held two edges (rx_runlen's glitch) means the
// second edge was lost: the run that follows it is two runs merged and its
// length says nothing. That run is class 0 whatever its length.
//
// Pipeline (runs can arrive on consecutive clocks, so it takes one per clock):
//   1  r = run -/+ b                         thresholds registered from ui
//   2  r against every threshold (16 comparisons, registered)
//   3  length and class from those           -> sym out
//   4  error of r against its class
//   5  the error rounded and scaled
//   6  ui += , b +=/-=  (held to what a MOST25 line can be; see there)
// The loops see their own correction 5 runs late. With steps of 1/64 and
// 1/128 that changes nothing; the regression (sim/run_rx.py) is the proof.
//
// The loops train on every run, framed or not, so noise trains them too. A
// 5 us burst of 0.6 UI runs on a line at the SP4 pulse-width limit (-0.15 UI)
// once left ui at 0.72 UI, a point the real line then held for good: the
// receiver never locked again. Two guards: ui and b stay inside what a
// MOST25 line can be, and after RELEARN clocks without a locked frame both
// start again from 17.0 and 0, as at power-up.
module rx_classify #(
    parameter RELEARN = 495000,     // clocks without a locked frame (5 ms at 99 MHz)
    parameter CLAMP   = 1           // 0 only in sim/run_rx.py, to test RELEARN alone
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       run_valid,
    input  wire [7:0] run_len,
    input  wire       run_level,
    input  wire       glitch,       // rx_runlen: this run's word held two edges (the next run is merged)
    input  wire [31:0] run_t,       // edge time, passed through with the symbol
    input  wire       locked,       // rx_framer: frames are locked
    output reg        sym_valid,
    output reg  [1:0] sym,          // 1, 2, 3; 0 = error
    output reg  [3:0] sym_len,      // the run in whole UI, 0..15 (= sym for classes 1..3)
    output reg        sym_level,
    output reg [15:0] ui_q,         // current UI estimate, Q8.8 (for status)
    output reg [31:0] sym_t         // sample time of the edge that ended this run
);
    reg signed [15:0] b;            // pulse-width bias, Q8.8

    // thresholds, re-registered every clock from ui_q: (k + 0.5) UI for k = 0..14
    reg signed [17:0] t05, t15, t25, u1, u2;
    reg signed [17:0] th [3:14];    // th[k] = (k + 0.5) UI, th[3] = 3.5 UI
    integer j;
    always @(posedge clk) begin
        t05 <= {2'b0, ui_q} >> 1;
        t15 <= {2'b0, ui_q} + ({2'b0, ui_q} >> 1);
        t25 <= ({2'b0, ui_q} << 1) + ({2'b0, ui_q} >> 1);
        th[3] <= ({2'b0, ui_q} << 1) + {2'b0, ui_q} + ({2'b0, ui_q} >> 1);
        u1  <= {2'b0, ui_q};
        u2  <= {2'b0, ui_q} << 1;
        for (j = 4; j <= 14; j = j + 1) th[j] <= th[j - 1] + u1;   // a clock behind per step: ui moves slowly
    end

    // the glitch flag belongs to the run AFTER the word that held two edges
    reg gpend;
    always @(posedge clk) gpend <= rst ? 1'b0 : (run_valid ? glitch : gpend);

    // ---- stage 1: bias-corrected run
    reg               v1, l1, g1;
    reg signed [17:0] r1;
    reg        [31:0] t1;
    wire signed [17:0] raw = {2'b0, run_len, 8'd0};
    always @(posedge clk) begin
        v1 <= run_valid & ~rst;
        l1 <= run_level;
        g1 <= gpend;
        t1 <= run_t;
        r1 <= run_level ? raw - b : raw + b;
    end

    // ---- stage 2: r against every threshold, registered (16 comparators
    // and a 16-way count in one clock were clk_s's slowest path)
    reg [15:0]        ge;                   // ge[k]: r >= (k + 0.5) UI
    reg               v1b, l1b, g1b;
    reg signed [17:0] r1b;
    reg        [31:0] t1b;
    integer k;
    always @(posedge clk) begin
        ge[0] <= r1 >= t05; ge[1] <= r1 >= t15; ge[2] <= r1 >= t25;
        for (k = 3; k <= 14; k = k + 1) ge[k] <= r1 >= th[k];
        ge[15] <= 1'b0;
        v1b <= v1 & ~rst; l1b <= l1; g1b <= g1; r1b <= r1; t1b <= t1;
    end

    // ---- stage 3: length in whole UI (0..15), then the class
    reg [3:0] n;
    integer m;
    always @* begin
        n = 4'd0;
        for (m = 0; m <= 14; m = m + 1)
            if (ge[m]) n = m[3:0] + 4'd1;
    end
    wire [1:0] c = (g1b || n == 4'd0 || n > 4'd3) ? 2'd0 : n[1:0];
    reg               v2, l2;
    reg [1:0]         c2;
    reg signed [17:0] r2, uk2;              // r, and the UI of its class (one or two)
    always @(posedge clk) begin
        v2 <= v1b & ~rst; l2 <= l1b; c2 <= c; r2 <= r1b; uk2 <= (n == 4'd2) ? u2 : u1;
        sym_valid <= v1b & ~rst; sym <= c; sym_len <= n; sym_level <= l1b; sym_t <= t1b;
    end

    // ---- stage 4: the error of r against its class (the subtract alone: with
    // the class mux and the rounding adds in one clock it was clk_s's slowest path)
    reg               v2b, l2b;
    reg [1:0]         c2b;
    reg signed [17:0] e;
    always @(posedge clk) begin
        v2b <= v2 & ~rst; l2b <= l2; c2b <= c2;
        e <= r2 - uk2;
    end

    // ---- stage 5: rounded, scaled error. Shifts sit in their own signed
    // registers: inside an expression with the unsigned ui_q, >>> would
    // silently turn into a logical shift. Rounded, not floored: a floor
    // biases ui low by half an LSB per step.
    reg               v3, l3;
    reg [1:0]         c3;
    reg signed [17:0] e6, e7;
    always @(posedge clk) begin
        v3 <= v2b & ~rst; l3 <= l2b; c3 <= c2b;
        e6 <= (e + 18'sd32) >>> 6;
        e7 <= (e + 18'sd64) >>> 7;
    end

    // ---- stage 6: loop update, held to what a MOST25 line can be:
    // ui  44.1/48 kHz +-0.1 % is 16.10..17.56 samples; kept in 15.5..18.25
    // b   SP4 allows +0.40 / -0.257 UI of pulse-width distortion, under
    //     7 samples; kept within +-7.5
    localparam signed [18:0] UI_MIN = 19'sd3968, UI_MAX = 19'sd4672;   // Q8.8
    localparam signed [18:0] B_MAX = 19'sd1920;
    wire signed [18:0] de = (c3 == 2'd1) ? {e6[17], e6} : {e7[17], e7};  // e covers two UI in class 2
    wire signed [18:0] db = {e7[17], e7};
    wire signed [18:0] ui_n = $signed({3'b0, ui_q}) + de;
    wire signed [18:0] b_n = l3 ? $signed({{3{b[15]}}, b}) + db : $signed({{3{b[15]}}, b}) - db;

    reg  [19:0] unl;                // clocks without a locked frame
    wire        relearn = (unl == RELEARN - 1);
    always @(posedge clk) unl <= (rst || locked || relearn) ? 20'd0 : unl + 20'd1;

    always @(posedge clk) begin
        if (rst || relearn) begin
            ui_q <= 16'd17 << 8;
            b    <= 16'sd0;
        end else if (v3 && (c3 == 2'd1 || c3 == 2'd2)) begin
            if (CLAMP) begin
                ui_q <= (ui_n < UI_MIN) ? UI_MIN[15:0] : (ui_n > UI_MAX) ? UI_MAX[15:0] : ui_n[15:0];
                b    <= (b_n < -B_MAX) ? -B_MAX[15:0] : (b_n > B_MAX) ? B_MAX[15:0] : b_n[15:0];
            end else begin
                ui_q <= ui_n[15:0];
                b    <= b_n[15:0];
            end
        end
    end
endmodule
