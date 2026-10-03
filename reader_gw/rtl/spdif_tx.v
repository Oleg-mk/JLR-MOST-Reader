// spdif_tx.v - the stereo as S/PDIF (IEC 60958-3), for the TOSLINK transmitter, on the frame
// train and the 1.26 ns grid.
//
// One S/PDIF frame per ring frame: 2 subframes x 32 time slots, biphase mark at 128 Fs. The
// half-cells come from nco_frame's ticks: one opens on every eighth tick (phase_n[2:0] == 0),
// so the stream is synchronous to the ring and nothing is resampled. The tick names the sample
// of the clock's 8 it falls on, and the line is put out as 8 samples a clock (word, bit 0
// first, for OSER8 as fs_fine does it): an edge sits on the 1.26 ns grid, not the 10.1 ns one.
//
// Subframe: slots 0..3 the preamble (8 half-cells, not biphase: X = 1110 0010 before a left
// sample, Y = 1110 0100 before a right one, Z = 1110 1000 before the left sample that starts a
// 192-frame channel-status block, each inverted when the line was high before it), slots 4..27
// the sample, 24 bit, LSB first, 28 validity (0 = valid), 29 user data (0), 30 channel status,
// 31 parity: even over slots 4..31. Channel status, the same for both channels: consumer, PCM,
// no copyright asserted (byte 0 = 04), category general, the ring's rate (byte 3 = 00 for
// 44.1 kHz, 02 for 48), 24-bit words (byte 4 = 0B), the rest zero.
//
// Every biphase bit cell opens with a transition; a 1 has a second one in the middle. The pair
// is latched at the tick of phase 0, where amp_out's engine latches its inputs. The line is
// held low while the train does not run (ring gone): the receiver unlocks, as it should.
// Taken from MOST25-to-AUDIO's spdif_tx.v (clk_r = 1024 Fs there); the coding is the same.
module spdif_tx (
    input  wire        clk,
    input  wire        run,                 // the frame train runs
    input  wire        tick,                // a tick in this clock...
    input  wire [2:0]  sub,                 // ...at this sample of its 8
    input  wire [9:0]  phase_n,             // the phase after the tick
    input  wire [47:0] lr,                  // L R, 24 bit each, L on top (amp_out's out_w)
    input  wire        rate48,              // 1 = 48 kHz ring, 0 = 44.1 (channel status byte 3)
    output reg  [7:0]  word,                // the line over this clock's 8 samples, bit 0 first
    output reg         out                  // the line after this clock
);
    reg  [47:0] s;                          // the pair on the way out
    reg  [7:0]  fr;                         // frame 0..191 of the channel-status block
    reg         whole;                      // the frame in progress began at half-cell 0 (not the
                                            // partial one run may start in): only those count
    reg         inv;                        // the line before this subframe's preamble
    wire        hc   = tick && phase_n[2:0] == 3'd0;     // a half-cell opens
    wire [6:0]  h    = phase_n[9:3];                     // half-cell 0..127 of the frame
    wire        subf = h[6];                             // 0 left, 1 right
    wire [4:0]  slot = h[5:1];                           // time slot 0..31
    wire        half = h[0];
    wire [23:0] smp  = subf ? s[23:0] : s[47:24];
    // channel status bit of this frame: bytes 0..4 = 04 00 00 (00|02) 0B, then zeros
    wire [39:0] cs   = {8'h0B, {6'd0, rate48, 1'b0}, 8'h00, 8'h00, 8'h04};   // byte 4 on top
    wire        c    = (fr < 8'd40) ? cs[fr[5:0]] : 1'b0;
    wire        par  = (^smp) ^ c;                       // V = U = 0
    wire        b    = (slot <= 5'd27) ? smp[slot - 5'd4] :
                       (slot == 5'd30) ? c :
                       (slot == 5'd31) ? par : 1'b0;     // 28 validity, 29 user data
    // preambles as the levels of half-cells 0..7 after a low line, bit i = half-cell i
    wire [7:0]  pz  = 8'b0001_0111;                      // Z: 1110 1000
    wire [7:0]  px  = 8'b0100_0111;                      // X: 1110 0010
    wire [7:0]  py  = 8'b0010_0111;                      // Y: 1110 0100
    wire [7:0]  pre = subf ? py : (fr == 8'd0) ? pz : px;
    wire        pre0 = h[2:0] == 3'd0 && slot == 5'd0;   // the preamble's first half-cell
    // the line after this half-cell opens
    wire        nxt  = pre0        ? pre[0] ^ out :
                       (slot < 5'd4) ? pre[h[2:0]] ^ inv :
                       !half       ? ~out :              // every cell opens with an edge
                       b           ? ~out : out;         // a 1: one more in the middle

    integer i;
    initial begin out = 1'b0; word = 8'd0; s = 48'd0; fr = 8'd0; whole = 1'b0; inv = 1'b0; end
    always @(posedge clk) begin
        if (!run) begin
            out <= 1'b0; word <= 8'd0; fr <= 8'd0; whole <= 1'b0; inv <= 1'b0;
        end else begin
            if (tick && phase_n == 10'd0) s <= lr;
            if (hc) begin
                if (pre0) inv <= out;                    // the line before the preamble
                out <= nxt;
                for (i = 0; i < 8; i = i + 1) word[i] <= (i >= sub) ? nxt : out;
                if (h == 7'd0) whole <= 1'b1;
                if (h == 7'd127 && whole) fr <= (fr == 8'd191) ? 8'd0 : fr + 8'd1;
            end else begin
                word <= {8{out}};
            end
        end
    end
endmodule
