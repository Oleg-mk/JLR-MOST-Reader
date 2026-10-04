// diag_cap.v - the log's capture buffer (LOGGING.md, "The capture buffer"): the line as it came,
// or whole frames, kept around a trigger and dumped as CAPTURE packets.
//
// NB blocks of 2^BW entries of 9 bits (NB = 16, BW = 11: 16 BSRAM blocks of 2048 x 9, 32768
// entries). Each block is an array of its own, so synthesis maps it to one 2048 x 9 BSRAM (one
// 64K x 9 array came out as 36 blocks of 16K x 1 in MOST25-to-AUDIO). The write enable is a
// registered one-hot, the address and data are registered once per group of 8 blocks; the
// read takes the block's own output register and two registered pick stages.
//
// Entries: runs mode {two-edge word, level, length 0..127}; frames mode {byte 0 of a frame,
// the byte}. States: 0 recording (runs, round and round), 1 running on after a trigger, 2 frozen,
// 3 dumping. A runs trigger runs on for half the buffer or RUN_MS, a frames trigger clears the
// buffer and records it full or for FRM_MS; then the dump goes out at once: the entries written
// since the buffer was last cleared, oldest first, 32 to a packet, then a trailer.
module diag_cap #(
    parameter NBW    = 4,                   // log2 blocks (16)
    parameter BW     = 11,                  // log2 entries a block
    parameter RUN_MS = 10,                  // a runs trigger: run on at most this long
    parameter FRM_MS = 50                   // a frames trigger: record at most this long
) (
    input  wire         clk,
    input  wire         rst,
    input  wire         ms,                 // pulse: a millisecond
    input  wire         run_v,              // a run, as an entry
    input  wire [8:0]   run_e,
    input  wire         frm_v,              // a frame byte, as an entry
    input  wire [8:0]   frm_e,
    input  wire         trig,               // pulse: a trigger
    input  wire [2:0]   trig_cause,
    input  wire         trig_frames,        // ...for a frames capture
    output reg  [1:0]   state,
    output reg          frames_mode,
    // events (pulses, with their argument)
    output reg          ev_trig, ev_refused, ev_dump, ev_done,
    output reg  [3:0]   a_trig,             // each event's argument, held until the next of its kind:
    output reg  [2:0]   a_ref,              //   cause and mode; the refused trigger's cause;
    output reg  [16:0]  a_dump,             //   entries in the dump; packets sent
    output reg  [15:0]  a_done,
    // packets for the log: pkt holds 32 entries (entry i at [9i +: 9]) or the trailer
    output reg          pkt_ready,
    input  wire         pkt_take,           // pulse: pkt was taken
    output reg  [15:0]  pkt_n,              // packet number, FFFF = the trailer
    output reg  [287:0] pkt,
    output reg  [31:0]  tr_entries,         // the trailer's fields
    output reg  [31:0]  tr_before,
    output reg  [2:0]   tr_cause,
    output reg          tr_frames
);
    localparam NB = 1 << NBW;
    localparam AW = NBW + BW;
    localparam [AW:0] N = {1'b1, {AW{1'b0}}};
    localparam GS = (NBW >= 3) ? 8 : NB;    // blocks in a group
    localparam NG = NB / GS;                // groups

    localparam [1:0] S_REC = 2'd0, S_RUN = 2'd1, S_FROZEN = 2'd2, S_DUMP = 2'd3;

    // ------------------------------------------------------------ what is written
    reg [AW-1:0] wptr;                      // next entry to write
    reg [AW:0]   count;                     // entries written since cleared, up to N
    reg [AW:0]   post;                      // entries left to run on
    reg [AW:0]   posted;                    // entries written since the trigger
    reg [15:0]   tms;                       // ms left to run on
    reg [2:0]    cause;
    reg          rec;                       // entries go in (recording or running on)
    wire         in_v = rec && (frames_mode ? frm_v : run_v);
    wire [8:0]   in_e = frames_mode ? frm_e : run_e;

    // the write, registered: a one-hot enable per block, address and data copied per group
    reg [NB-1:0] we_oh;
    reg [BW-1:0] wa_g [0:NG-1] /* synthesis syn_preserve = 1 */;
    reg [8:0]    wd_g [0:NG-1] /* synthesis syn_preserve = 1 */;
    integer g;
    always @(posedge clk) begin
        we_oh <= (in_v && !rst) ? ({{(NB-1){1'b0}}, 1'b1} << (wptr >> BW)) : {NB{1'b0}};
        for (g = 0; g < NG; g = g + 1) begin
            wa_g[g] <= wptr[BW-1:0];
            wd_g[g] <= in_e;
        end
    end

    // the read, for the dump
    reg  [AW-1:0] raddr;
    reg  [BW-1:0] ra_g [0:NG-1] /* synthesis syn_preserve = 1 */;
    reg  [AW-1:0] ra_q, ra_q2;              // the address, following the data down the pipe
    wire [8:0]    rq [0:NB-1];
    always @(posedge clk) begin
        for (g = 0; g < NG; g = g + 1) ra_g[g] <= raddr[BW-1:0];
        ra_q <= raddr; ra_q2 <= ra_q;
    end
    genvar b;
    generate
        for (b = 0; b < NB; b = b + 1) begin : blk
            reg [8:0] m [0:(1 << BW) - 1];
            reg [8:0] q;
            always @(posedge clk) if (we_oh[b]) m[wa_g[b / GS]] <= wd_g[b / GS];
            always @(posedge clk) q <= m[ra_g[b / GS]];
            assign rq[b] = q;
        end
    endgenerate
    // pick: within a group (registered), then the group (registered). ra_g -> q is one clock,
    // the address that went with it is ra_q2 when q is out
    reg [8:0] pk1 [0:NG-1];
    reg [AW-1:0] ra_q3;
    reg [8:0] pk2;
    integer gi;
    always @(posedge clk) begin
        for (gi = 0; gi < NG; gi = gi + 1) pk1[gi] <= rq[gi * GS + ((ra_q2 >> BW) % GS)];
        ra_q3 <= ra_q2;
        pk2 <= pk1[(ra_q3 >> BW) / GS];
    end

    // ------------------------------------------------------------ states
    // The dump, packet by packet: a packet's count is fixed when it starts (32, or what is left),
    // its reads go out one a clock, its entries shift in from the top of pkt as they come, and a
    // short last packet shifts zeros in after them until its first entry is at the bottom.
    reg  [AW:0]  rd_left;                   // entries still to dump after the packet being staged
    reg  [3:0]   rv_pipe;                   // a read is in flight at each pipe stage
    reg  [5:0]   pk_left;                   // reads still to issue for this packet
    reg  [5:0]   pk_cnt;                    // entries in this packet
    reg  [5:0]   got;                       // entries arrived
    reg  [5:0]   pad;                       // zeros still to shift in
    reg  [15:0]  npk;                       // packet being staged
    reg  [1:0]   ds;                        // 0 start a packet, 1 read it, 2 pad it, 3 ready
    reg          trail;
    wire         rd_ge32 = |rd_left[AW:5];
    wire         issue = state == S_DUMP && ds == 2'd1 && pk_left != 6'd0;
    always @(posedge clk) rv_pipe <= rst ? 4'd0 : {rv_pipe[2:0], issue};

    always @(posedge clk) begin
        ev_trig <= 1'b0; ev_refused <= 1'b0; ev_dump <= 1'b0; ev_done <= 1'b0;
        if (rst) begin
            state <= S_REC; frames_mode <= 1'b0; rec <= 1'b1; wptr <= 0; count <= 0; post <= 0; posted <= 0;
            tms <= 16'd0; cause <= 3'd0; raddr <= 0; rd_left <= 0; pk_left <= 6'd0; pk_cnt <= 6'd0; got <= 6'd0;
            pad <= 6'd0; npk <= 16'd0; ds <= 2'd0; trail <= 1'b0; pkt_ready <= 1'b0; pkt_n <= 16'd0;
            pkt <= 288'd0; tr_entries <= 32'd0; tr_before <= 32'd0; tr_cause <= 3'd0; tr_frames <= 1'b0;
            a_trig <= 4'd0; a_ref <= 3'd0; a_dump <= 17'd0; a_done <= 16'd0;
        end else begin
            // the write side
            if (in_v) begin
                wptr  <= wptr + 1'b1;
                if (count != N) count <= count + 1'b1;
                if (state == S_RUN) begin
                    posted <= posted + 1'b1;
                    if (post != 0) post <= post - 1'b1;
                end
            end
            if (state == S_RUN && ms && tms != 16'd0) tms <= tms - 16'd1;

            case (state)
            S_REC: if (trig) begin
                state <= S_RUN; cause <= trig_cause; posted <= 0; tms <= trig_frames ? FRM_MS : RUN_MS;
                ev_trig <= 1'b1; a_trig <= {trig_frames, trig_cause};
                if (trig_frames) begin
                    frames_mode <= 1'b1; wptr <= 0; count <= 0; post <= N;
                end else begin
                    post <= {2'b01, {(AW-1){1'b0}}};
                end
            end
            S_RUN: begin
                if (trig) begin ev_refused <= 1'b1; a_ref <= trig_cause; end
                if ((post == 1 && in_v) || post == 0 || (ms && tms == 16'd1) || tms == 16'd0) begin
                    state <= S_FROZEN; rec <= 1'b0;
                end
            end
            S_FROZEN: begin
                if (trig) begin ev_refused <= 1'b1; a_ref <= trig_cause; end
                // the dump: the entries written since the buffer was last cleared, oldest first
                state <= S_DUMP;
                rd_left <= count; raddr <= wptr - count[AW-1:0];
                npk <= 16'd0; ds <= 2'd0; trail <= 1'b0;
                tr_entries <= {{(31 - AW){1'b0}}, count};
                tr_before <= {{(31 - AW){1'b0}}, count - posted};
                tr_cause <= cause; tr_frames <= frames_mode;
                ev_dump <= 1'b1; a_dump <= {{(16 - AW){1'b0}}, count};
            end
            S_DUMP: begin
                if (trig) begin ev_refused <= 1'b1; a_ref <= trig_cause; end
                if (issue) begin raddr <= raddr + 1'b1; pk_left <= pk_left - 6'd1; end
                if (rv_pipe[3]) begin pkt <= {pk2, pkt[287:9]}; got <= got + 6'd1; end
                case (ds)
                2'd0: begin                          // start a packet, or the trailer
                    pkt <= 288'd0; got <= 6'd0;
                    if (rd_left == 0) begin
                        trail <= 1'b1; pkt_n <= 16'hFFFF; pkt_ready <= 1'b1; ds <= 2'd3;
                    end else begin
                        pk_left <= rd_ge32 ? 6'd32 : rd_left[5:0];
                        pk_cnt  <= rd_ge32 ? 6'd32 : rd_left[5:0];
                        pad     <= rd_ge32 ? 6'd0 : 6'd32 - rd_left[5:0];
                        rd_left <= rd_ge32 ? rd_left - 6'd32 : {(AW+1){1'b0}};
                        ds <= 2'd1;
                    end
                end
                2'd1: if (pk_left == 6'd0 && rv_pipe == 4'd0 && got == pk_cnt) ds <= 2'd2;
                2'd2: begin                          // a short packet: its entries down to the bottom
                    if (pad != 6'd0) begin pkt <= {9'd0, pkt[287:9]}; pad <= pad - 6'd1; end
                    else begin pkt_ready <= 1'b1; pkt_n <= npk; ds <= 2'd3; end
                end
                2'd3: if (pkt_ready && pkt_take) begin
                    pkt_ready <= 1'b0;
                    if (trail) begin
                        // done: cleared, recording runs again
                        state <= S_REC; frames_mode <= 1'b0; rec <= 1'b1; wptr <= 0; count <= 0;
                        ev_done <= 1'b1; a_done <= npk;
                    end else begin
                        npk <= npk + 16'd1; ds <= 2'd0;
                    end
                end
                endcase
            end
            endcase
        end
    end
endmodule
