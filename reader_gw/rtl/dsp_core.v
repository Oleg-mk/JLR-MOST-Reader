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
//      the memories; a product from the previous instruction is accumulated
//   B  the memories' data is valid: operands into the multiplier, or a load,
//      a store, a move, an output; the next instruction is fetched
//   C  the product is formed (registered); STR writes its remainder
// So a store or an output sees every product before it, and a read sees
// every write before it. The program takes 449 of the 1024 clocks of a frame
// (dsp_asm.py asserts < 1000); `overrun` is set if a frame starts before it
// has finished.
//
// D, the engine's own data (filter states, gains), is two copies of one
// memory, written together, so that one clock can read two words. It starts
// at zero, and it is never cleared: states and gains carry on through a reset
// of the ring domain as the audio does.
module dsp_core (
    input  wire         clk,                // clk_r
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

    // ------------------------------------------------------ inputs, datapath
    reg  [143:0] in_r;
    wire [23:0]  in24 = in_r[143 - 24 * ia[2:0] -: 24];
    wire [31:0]  in32 = {{3{in24[23]}}, in24, 5'd0};

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
    // OUT: round(acc >> 33), saturated to 24 bit
    wire [71:0] ar = acc + 72'h1_0000_0000;
    wire [38:0] of = ar[71:33];
    wire        o_hi = ~of[38] & (|of[37:23]);
    wire        o_lo =  of[38] & ~(&of[37:23]);
    wire [23:0] o24 = o_hi ? 24'h7FFFFF : o_lo ? 24'h800000 : of[23:0];

    always @* begin
        dwe = 1'b0; dwa = ib; dwd = 32'd0;
        if (running && ph == 2'd1) begin
            case (op)
                OP_IN:   begin dwe = 1'b1; dwd = in32; end
                OP_MACS: begin dwe = 1'b1; dwa = ib + 7'd1; dwd = dyq; end
                OP_STR:  begin dwe = 1'b1; dwd = y32; end
                OP_MOV:  begin dwe = 1'b1; dwd = dxq; end
                default: ;
            endcase
        end else if (running && ph == 2'd2 && op == OP_STR) begin
            dwe = 1'b1; dwa = ia; dwd = {4'd0, rem};
        end
    end

    initial begin running = 1'b0; overrun = 1'b0; ph = 2'd0; pc = 8'd0; pend = 1'b0; end
    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0; overrun <= 1'b0; ph <= 2'd0; pc <= 8'd0; pend <= 1'b0; out_w <= 48'd0;
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
                        OP_STR: rem <= r28;
                        OP_OUT: out_w[47 - 24 * ia[0] -: 24] <= o24;
                        default: ;
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
