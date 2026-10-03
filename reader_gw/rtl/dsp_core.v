// dsp_core.v - a small multiply-accumulate engine: one fixed program per ring frame.
//
// It does to our output what the factory amplifier does to its speakers:
// tone on the main source, then three sources mixed into L and R with gains
// that move smoothly. The program, the memory map and a bit-exact model are
// in sim/dsp_asm.py; dsp_prog.vh is generated from it. The host computes the
// coefficients and gains; this engine only multiplies and adds.
//
// Words are 32 bit, Q4.28 (1.0 = 2^28); products Q8.56 in a 72-bit
// accumulator. One instruction takes three clocks:
//   A  the instruction is valid (ROM, registered); its C and D addresses go to
//      the memories; a product from the previous instruction is accumulated;
//      what it will write to D in B is decoded (registered with it)
//   B  the memories' data is valid: operands into the multiplier, or a load,
//      a store, a move, OUT's first step; the next instruction is fetched
//   C  the product is formed (registered); STR writes its remainder
// So a store or an output sees every product before it, and a read sees
// every write before it. The program takes 449 clocks (dsp_asm.py asserts
// < 1000) of the about 2062 clk_s of a frame; `overrun` is set if a frame
// starts before it has finished.
//
// OUT is spread over three clocks: B takes acc's rounding bit and which of
// its low bytes are all ones, C adds the rounding bit with those carries
// (acc >> 33, plus 1 if bit 32 is set), and the A after it saturates and
// writes out_w - two clocks after B, where it used to be written in one. At
// clk_s (99 MHz) the one-clock form missed by 6.5 ns: the add of 2^32 maps to
// a ripple of LUTs, not the carry chain, 16 deep before the saturation. acc
// holds from OUT's B until the next instruction's B at the earliest (OUT
// starts no product), so all three clocks see the same acc. out_w is read
// only after the program has ended (spdif_tx at the next frame start, the
// testbenches when running falls), so the two clocks are not seen outside.
//
// D, the engine's own data (filter states, gains), is two copies of one
// memory, written together, so that one clock can read two words. It starts
// at zero, and it is never cleared: states and gains carry on through a reset
// of the ring domain as the audio does.
module dsp_core (
    input  wire         clk,                // clk_s
    input  wire         rst,
    input  wire         start,              // one clock per frame: latch in_w, run
    input  wire [143:0] in_w,               // s0L s0R s1L s1R s2L s2R, 24 bit each, s0L on top
    output wire [5:0]   c_addr,             // coefficient read address...
    input  wire [31:0]  c_q,                // ...and its word, one clock later
    output reg  [47:0]  out_w,              // L R, 24 bit each, L on top
    output reg          running,
    output reg          overrun             // a frame started before the program ended (sticky)
);
`include "dsp_prog.vh"
    localparam [3:0] OP_IN = 4'd1, OP_LDE = 4'd2, OP_ADZ = 4'd3, OP_MACZ = 4'd4, OP_MAC = 4'd5,
                     OP_MACS = 4'd6, OP_MACDZ = 4'd7, OP_MACD = 4'd8, OP_STR = 4'd9,
                     OP_MOV = 4'd10, OP_OUT = 4'd11, OP_END = 4'd15;

    // ------------------------------------------------------------ program
    reg  [7:0]  pc;                         // address at the ROM
    reg  [17:0] rom_q;
    always @(posedge clk) rom_q <= dsp_prog(pc);

    reg  [1:0]  ph;                         // 0 A, 1 B, 2 C, 3 the first fetch
    reg  [17:0] ir;                         // the instruction in B and C
    wire [3:0]  op = ir[17:14];
    wire [6:0]  ia = ir[13:7];
    wire [6:0]  ib = ir[6:0];
    assign c_addr = rom_q[12:7];            // presented in A

    // ------------------------------------------------------ inputs
    reg  [143:0] in_r;

    // -------------------------------------------- the D write, decoded in A
    // rom_q holds an instruction from its A to its C (pc moves at the end of B,
    // rom_q follows a clock later), so these, loaded from rom_q on every clock,
    // are in B and C what ir is. Decoded from ir in B, the input sample's 6-way
    // pick and the op's write mux sat in one clock before the memory (0.35 ns
    // short at clk_s); from here the write data is one mux of registers and of
    // the two late inputs (acc's saturation, the D memory's output).
    // rom_q is the program ROM's own output, with no register after it (its
    // data comes about 2.3 ns after the clock), so the sample is picked by a
    // plain mux on constant slices: written as the part-select at 143 - 24 k,
    // Gowin built the index as an adder and a one-hot decode, 7.4 ns of LUTs.
    wire [3:0]  op_n = rom_q[17:14];
    reg  [23:0] in24_n;
    always @* begin
        case (rom_q[9:7])                   // IN's a: 0..5 (dsp_asm.py); 6 and 7 never come
            3'd0:    in24_n = in_r[143:120];
            3'd1:    in24_n = in_r[119:96];
            3'd2:    in24_n = in_r[95:72];
            3'd3:    in24_n = in_r[71:48];
            3'd4:    in24_n = in_r[47:24];
            default: in24_n = in_r[23:0];
        endcase
    end
    reg         d_wb;                       // op writes D in B: IN, MACS, STR or MOV
    reg         d_macs, d_str, d_mov, d_out;    // op is MACS / STR / MOV / OUT
    reg  [6:0]  dwa_b;                      // B's write address: b, b + 1 for MACS
    reg  [31:0] in32_q;                     // IN's sample, Q4.28
    always @(posedge clk) begin
        d_wb   <= op_n == OP_IN || op_n == OP_MACS || op_n == OP_STR || op_n == OP_MOV;
        d_macs <= op_n == OP_MACS;
        d_str  <= op_n == OP_STR;
        d_mov  <= op_n == OP_MOV;
        d_out  <= op_n == OP_OUT;
        dwa_b  <= (op_n == OP_MACS) ? rom_q[6:0] + 7'd1 : rom_q[6:0];
        in32_q <= {{3{in24_n[23]}}, in24_n, 5'd0};
    end

    // ------------------------------------------------------------ D memory
    reg  [31:0] dmx [0:127];
    reg  [31:0] dmy [0:127];
    reg  [31:0] dxq, dyq;
    reg         dwe;
    reg  [6:0]  dwa;
    reg  [31:0] dwd;
    integer i;
    initial for (i = 0; i < 128; i = i + 1) begin dmx[i] = 32'd0; dmy[i] = 32'd0; end
    always @(posedge clk) begin
        if (dwe) begin dmx[dwa] <= dwd; dmy[dwa] <= dwd; end
        dxq <= dmx[rom_q[13:7]];            // read in A, valid in B
        dyq <= dmy[rom_q[6:0]];
    end

    // ------------------------------------------------------------ datapath
    reg  [71:0] acc;
    reg  [31:0] mx, my;
    reg  [63:0] prod;
    reg         pend, pz;                   // a product waits to be accumulated; it starts a sum
    reg  [27:0] rem;
    wire [71:0] prod72 = {{8{prod[63]}}, prod};

    // STR: acc >> 28, saturated to 32 bit; the remainder unless saturated
    wire [43:0] yf = acc[71:28];
    wire        y_hi = ~yf[43] & (|yf[42:31]);
    wire        y_lo =  yf[43] & ~(&yf[42:31]);
    wire [31:0] y32 = y_hi ? 32'h7FFFFFFF : y_lo ? 32'h80000000 : yf[31:0];
    wire [27:0] r28 = (y_hi | y_lo) ? 28'd0 : acc[27:0];

    // The remainder is taken on every clock: it is read only in the C right
    // after a STR's B (below), and there it holds what B's acc gave, as when
    // it was loaded in that B alone. That enable took the frame start (start,
    // from nco_frame's phase across the chip) and the op: 9 ns at clk_s.
    always @(posedge clk) rem <= r28;

    // B writes IN's sample, MACS's delay-line word, STR's result, MOV's word;
    // C writes STR's remainder. The data matters only where dwe is set. The
    // inputs that come last, STR's result through acc's saturation and the D
    // memory's words (like the ROM's, about 2.3 ns after the clock), are
    // picked nearest the memory; the rest are registers.
    always @* begin
        dwe = running && ((ph == 2'd1 && d_wb) || (ph == 2'd2 && d_str));
        dwa = ph[1] ? ia : dwa_b;
        dwd = (d_str && !ph[1]) ? y32 :
              d_mov  ? dxq :
              d_macs ? dyq :
              ph[1]  ? {4'd0, rem} : in32_q;
    end

    // OUT: round(acc >> 33), saturated to 24 bit. acc + 2^32 leaves bits
    // 31..0 alone and carries bit 32 into bit 33, so acc[71:33] + acc[32] is
    // what is shifted down. B registers that bit and which of the four low bytes
    // of acc[71:33] are all ones; C carries it into each bit of of2: bit j flips
    // when the rounding bit, every byte below j's and j's own bits below it are
    // all ones. Each carry is one AND of at most 11 registers, so it is two or
    // three LUTs deep; as a chain it was the 16-deep ripple. The A after
    // saturates of2.
    reg         o1 = 1'b0, o2 = 1'b0;       // an OUT in its C / in the A after
    reg         k1, k2;                     // which output
    reg         r1;                         // acc[32]
    reg  [3:0]  a1;                         // acc[40:33], [48:41], [56:49], [64:57] all ones
    reg  [38:0] of2;                        // acc[71:33] + acc[32]
    function [38:0] round_hi;               // h + r, a carry-in for each bit
        input [38:0] h;
        input        r;
        input [3:0]  a;
        reg   [3:0]  am;
        reg   [38:0] hm;
        integer      j;
        begin
            for (j = 0; j < 39; j = j + 1) begin
                am = (j >= 32) ? 4'hF : (4'd1 << (j >> 3)) - 4'd1;      // the bytes below j's (all four for the top byte)
                hm = ((39'd1 << (j & 7)) - 39'd1) << (j - (j & 7));     // j's byte below j
                round_hi[j] = h[j] ^ (r & (&(a | ~am)) & (&(h | ~hm)));
            end
        end
    endfunction
    wire        o_hi = ~of2[38] & (|of2[37:23]);
    wire        o_lo =  of2[38] & ~(&of2[37:23]);
    wire [23:0] o24 = o_hi ? 24'h7FFFFF : o_lo ? 24'h800000 : of2[23:0];
    always @(posedge clk) begin
        // an OUT executes in B exactly where the case below runs its B
        o1 <= !rst && !start && running && ph == 2'd1 && d_out;
        o2 <= o1 && !rst;
        k1 <= ia[0]; k2 <= k1;
        r1 <= acc[32];
        a1 <= {&acc[64:57], &acc[56:49], &acc[48:41], &acc[40:33]};
        of2 <= round_hi(acc[71:33], r1, a1);
        if (rst) out_w <= 48'd0;
        else if (o2) begin
            if (k2) out_w[23:0] <= o24;     // R
            else    out_w[47:24] <= o24;    // L
        end
    end

    initial begin running = 1'b0; overrun = 1'b0; ph = 2'd0; pc = 8'd0; pend = 1'b0; end
    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0; overrun <= 1'b0; ph <= 2'd0; pc <= 8'd0; pend <= 1'b0;
        end else if (start) begin
            if (running) overrun <= 1'b1;
            in_r <= in_w; pc <= 8'd0; ph <= 2'd3; running <= 1'b1; pend <= 1'b0;
        end else if (running) begin
            case (ph)
                2'd3: ph <= 2'd0;
                2'd0: begin
                    ir <= rom_q;
                    if (pend) begin
                        acc <= pz ? prod72 : acc + prod72;
                        pend <= 1'b0;
                    end
                    ph <= 2'd1;
                end
                2'd1: begin
                    case (op)
                        OP_LDE: acc <= {44'd0, dyq[27:0]};
                        OP_ADZ: acc <= {{12{c_q[31]}}, c_q, 28'd0};
                        OP_MACZ, OP_MAC, OP_MACS: begin
                            mx <= c_q; my <= dyq; pend <= 1'b1; pz <= (op == OP_MACZ);
                        end
                        OP_MACDZ, OP_MACD: begin
                            mx <= dxq; my <= dyq; pend <= 1'b1; pz <= (op == OP_MACDZ);
                        end
                        default: ;              // IN, STR, MOV: the D write above;
                                                // OUT: the three clocks above
                    endcase
                    pc <= pc + 8'd1;
                    if (op == OP_END) begin running <= 1'b0; ph <= 2'd0; end
                    else ph <= 2'd2;
                end
                default: begin                  // C
                    prod <= $signed(mx) * $signed(my);
                    ph <= 2'd0;
                end
            endcase
        end
    end
endmodule
