// rx_runlen.v - run lengths of the oversampled MOST25 line.
//
// Input: 8 samples per clock from the IDES8 deserialiser, bit 0 = earliest.
// At 792 Msps one UI is 16.1 (48 kHz) or 17.5 (44.1 kHz) samples, and the
// shortest legal pulse at the receiver output is 0.743 UI (SP4 tpwv4 min),
// i.e. at least 11 samples. So a clean input has at most one edge per word.
// Two or more edges in one word can only be a glitch and are flagged.
//
// Output, one strobe per edge: the length in samples of the run that just
// ended, that run's level, and the absolute time of the edge that ended it,
// in samples (1.26 ns at 792 Msps): word counter x 8 + the index of the
// first sample of the new level. That time keeps the full resolution of the
// sampler; anything downstream that has to reproduce a ring edge (the frame
// rate for the clock multiplier) places it by this time, not by the clock
// edge on which it happened to be seen.
module rx_runlen (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] samp,
    input  wire [28:0] wc,         // word counter, +1 per clock (the time base)
    output reg        run_valid,
    output reg  [7:0] run_len,     // samples, saturates at 255
    output reg        run_level,   // level of the run that ended
    output reg        glitch,      // >1 edge in one word
    output reg [31:0] run_t        // sample time of the edge that ended the run
);
    reg       prev;                // last sample of the previous word
    reg [7:0] cnt;                 // samples since the last edge, up to end of previous word

    wire [7:0] tr = samp ^ {samp[6:0], prev};   // tr[i]: edge between sample i-1 and i

    // position of the first edge, and whether there is more than one
    reg [2:0] p;
    reg       any, many;
    integer i;
    always @* begin
        p = 3'd0; any = 1'b0; many = 1'b0;
        for (i = 7; i >= 0; i = i - 1)
            if (tr[i]) begin
                if (any) many = 1'b1;
                any = 1'b1;
                p   = i[2:0];
            end
    end

    wire [8:0] len = {1'b0, cnt} + {6'd0, p};

    always @(posedge clk) begin
        if (rst) begin
            prev <= 1'b0; cnt <= 8'd0;
            run_valid <= 1'b0; run_len <= 8'd0; run_level <= 1'b0; glitch <= 1'b0;
            run_t <= 32'd0;
        end else begin
            prev      <= samp[7];
            run_valid <= any;
            glitch    <= many;
            if (any) begin
                run_len   <= len[8] ? 8'hFF : len[7:0];
                run_level <= ~samp[p];
                run_t     <= {wc, p};
                cnt       <= 8'd8 - {5'd0, p};
            end else begin
                cnt <= (cnt > 8'd247) ? 8'hFF : cnt + 8'd8;
            end
        end
    end
endmodule
