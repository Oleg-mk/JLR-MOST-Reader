// ctrl_decode.v - the control channel, read by the FPGA itself: what the head unit tells
// the amplifier becomes amp_out's commands, as the host's packets did in MOST25-to-AUDIO.
//
// Block: frame bytes 61 and 62 of the 16 frames of a block (frame k carries bytes 2k, 2k+1;
// MOST Book 2 Fig 5.12), taken when the block's last frame completes with the block index
// known and the receiver locked, as ctrl_uart.v took it. Layout (CORE Table 3-6, 3.4.6.2):
// 4-5 target, 6-7 source, 8 message type, 9 FBlockID, 10 InstID, 11 FktID[11:4],
// 12 FktID[3:0]:OPType, 13 TelID:TelLen, 14..25 Data0..11.
//
// Integrity (audit R02). The block's CRC cannot be checked: its polynomial is not known. A
// line-code error already costs the block (rx_framer drops blk_known). What biphase mark lets
// through unseen is a lost mid-cell transition, a 1 read as 0, and that the frame parity
// catches: its sense is not documented, but it is one value on every clean frame of a ring, so
// it is learnt here - PAR_LEARN locked frames of one parity in a row - and from then on a block
// with a frame of the other parity is dropped. PAR_BAD such frames in a row mean the premise
// was wrong (a parity that is not over the whole frame), and the sense is forgotten and learnt
// anew; a ring whose parity varies is thus never filtered. The CRC comes once a capture gives it.
//
// A block is a telegram under the rules the host used (virtual_most_source/control.py is the
// reference, cross-checked against the C host): message type 0, a data byte other than 00/FF,
// TelID 0 (every message here fits one telegram, so segments are left alone), target
// 0x0010..0x0FFF, source logical or static, TelLen at most 12 (11 to a group). The *Ack OPTypes
// carry a 2-byte SenderHandle first; the payload starts after it.
//
// Messages, by FBlock, FktID and OPType. The InstID is not checked at all (audit R07: a request
// may name instance 0 or 0xFF and the answer the real one), and the addresses only pair a
// request with its answer: a request's device is its target, an answer's its source.
//   0x22 0x111 Connect      StartResult(Ack) [SinkNr, SrcDelay, ch...]  sink 1..3 -> stream 0..2;
//                           the position takes effect at once and is unconfirmed until the
//                           device's Result [SinkNr]; its Error turns every unconfirmed Connect
//                           to that device off (audit R08); a Result with no Connect on, or
//                           from another device, changes nothing
//   0x22 0x110 SinkInfo     Status [SinkNr, DataType, Resolution, AudioChannels, SinkDelay, ch...]
//                           the device's own word on its sink, confirmed as it comes; any other
//                           SinkInfo on the sink means nothing is known: off
//   0x22 0x112 DisConnect   StartResult(Ack) [SinkNr]                  off, if to the device the position came from
//   0x22 0x113 Mute         Set/SetGet/Status [SinkNr, Status]          sink 0 = all, kept for every stream,
//                                                                      connected or not (audit R04); bit 0 = mute
//   0x22 0x46D SpeakerLevel Set/SetGet/Status [param, SinkNr, dB...]    the loudest speaker, signed dB
//   0xF0 0x409 (JLR)        Status                                     byte 2 audio, byte 8 nav/phone, raw
// Formats (audit R09): from SinkInfo the full tuple, PCM only, 2 or 3 bytes a sample, 1 or 2
// channels, the list exactly Resolution x AudioChannels long. A Connect carries the list alone;
// 4 channels are taken as 16-bit stereo and 2 as 16-bit mono - the formats JLR is on record
// with (STX 5.4.1.1: L-Hi, L-Lo, R-Hi, R-Lo) - and a list of 3 or 6, which could be 24-bit
// stereo or three 16-bit channels, is refused until a SinkInfo names the format. Channels are
// 0..59, ascending; frame byte = channel + 1 (Data Byte k is frame byte k+1).
// A stream's gain, as the host chose it: muted -> 0; its own SpeakerLevel (dB); else, streams 1
// and 2, 0x409 byte 8; else the volume: SpeakerLevel to sink 1, else 0x409 byte 2; else the
// stream's start-up level (GAIN_DEF_*: the user's decision, a third of full volume or less for
// the main source, their own figures for the announcement streams), which is also what the
// first coefficient set after reset carries, so a Connect is heard before any level message.
// The dB -> word and raw -> word tables are gain_rom.vh, written by sim/gain_tables.py, which
// is also their model. Positions survive a lost lock (audit R06: a gap must not silence the one
// output); a ring restart takes the FPGA's supply with it and so clears everything.
//
// Every change of a stream's position sends command 01 for it; every accepted level or mute
// message rewrites the whole coefficient set as the host did: 47 words, straight biquads,
// k x gain per stream and output, 1 - k, the commit with the last, all carrying the set's tag
// (amp_out switches banks only on a whole set of one tag: audit R03). Commands leave one a
// clock, about 60 clocks for a set - long before the next block can complete, 16 frames later.
// sim/ctrl_model.py is this module's model, frame for frame; sim/run_ctrl.py checks them.
module ctrl_decode #(
    parameter AMP_FBLOCK = 8'h22,
    parameter JLR_FBLOCK = 8'hF0,
    parameter PAR_LEARN  = 64,              // locked frames of one parity before its sense counts as known
    parameter PAR_BAD    = 4                // frames of the other parity in a row that forget it again
) (
    input  wire        clk,
    input  wire        rst,
    // frame bytes from rx_framer
    input  wire        byte_we,
    input  wire [5:0]  byte_addr,
    input  wire [7:0]  byte_data,
    input  wire        frame_done,
    input  wire        frame_par,           // with frame_done: the XOR of the frame's bits 4..511
    input  wire [3:0]  blk_idx,
    input  wire        blk_known,
    input  wire        locked,
    // the command bus into amp_out (what host_cmd gave: ok, cmd, p)
    output reg         ok,
    output reg  [7:0]  cmd,
    output reg  [55:0] p,
    // status
    output reg         tel,                 // pulse: the block carried a telegram
    output reg         hit,                 // pulse: ...one of ours
    output reg         dropped,             // pulse: a block completed, but a frame's parity was off
    output wire        par_known_o,         // the ring's parity sense is known and checked
    output wire        busy                 // commands pending or going out
);
`include "gain_rom.vh"
    integer k;

    // ---------------------------------------------------------- the block, 32 bytes
    reg [7:0] blk [0:31];
    always @(posedge clk) begin
        if (byte_we && byte_addr == 6'd61) blk[{blk_idx, 1'b0}] <= byte_data;
        if (byte_we && byte_addr == 6'd62) blk[{blk_idx, 1'b1}] <= byte_data;
    end

    // ---------------------------------------------------------- the frame parity, learnt
    reg        par_known, par_sense, par_last, blk_bad;
    reg [7:0]  par_cnt;                     // frames of the same parity in a row, while learning
    reg [3:0]  bad_run;                     // frames of the other parity in a row, once known
    wire       bad_now = par_known && frame_par != par_sense;
    assign par_known_o = par_known;
    always @(posedge clk) begin
        if (rst) begin
            par_known <= 1'b0; par_sense <= 1'b0; par_last <= 1'b0; par_cnt <= 8'd0; bad_run <= 4'd0;
            blk_bad <= 1'b0;
        end else if (frame_done) begin
            if (blk_idx == 4'd15) blk_bad <= 1'b0;                  // the next block starts clean
            else if (locked && bad_now) blk_bad <= 1'b1;
            if (locked) begin
                if (!par_known) begin
                    par_last <= frame_par;
                    if (frame_par == par_last) begin
                        if (par_cnt == PAR_LEARN - 1) begin
                            par_known <= 1'b1; par_sense <= frame_par; bad_run <= 4'd0; par_cnt <= 8'd0;
                        end else par_cnt <= par_cnt + 8'd1;
                    end else par_cnt <= 8'd1;
                end else if (bad_now) begin
                    if (bad_run == PAR_BAD - 1) begin
                        par_known <= 1'b0; par_cnt <= 8'd0; bad_run <= 4'd0;
                    end else bad_run <= bad_run + 4'd1;
                end else bad_run <= 4'd0;
            end
        end
    end
    reg done;
    always @(posedge clk) begin
        done    <= frame_done && locked && blk_known && blk_idx == 4'd15 && !blk_bad && !bad_now && !rst;
        dropped <= frame_done && locked && blk_known && blk_idx == 4'd15 && (blk_bad || bad_now) && !rst;
    end

    // ---------------------------------------------------------- E1: the fields
    reg        e1;
    reg [15:0] tgt, src;
    reg [7:0]  mtype, fb;
    reg [11:0] fkt;
    reg [3:0]  op, telid, tellen;
    reg [7:0]  d [0:11];
    reg [16:0] idle_b;                      // data area byte 9 + k is 00 or FF
    always @(posedge clk) begin
        e1 <= done && !rst;
        if (done) begin
            tgt    <= {blk[4], blk[5]};
            src    <= {blk[6], blk[7]};
            mtype  <= blk[8];
            fb     <= blk[9];
            fkt    <= {blk[11], blk[12][7:4]};
            op     <= blk[12][3:0];
            telid  <= blk[13][7:4];
            tellen <= blk[13][3:0];
            for (k = 0; k < 12; k = k + 1) d[k] <= blk[14 + k];
            for (k = 0; k < 17; k = k + 1) idle_b[k] <= blk[9 + k] == 8'h00 || blk[9 + k] == 8'hFF;
        end
    end

    // ---------------------------------------------------------- E2: a telegram? its payload
    wire grp    = tgt[15:8] == 8'h03;                                    // 0x0300..0x03FF
    wire tgt_ok = tgt[15:12] == 4'd0 && tgt[11:4] != 8'd0;              // 0x0010..0x0FFF
    wire src_ok = src[15:12] == 4'd0 && src[11:4] != 8'd0 &&            // 0x0010..0x02FF, 0x0500..0x0FFF
                  src[11:8] != 4'h3 && src[11:8] != 4'h4;
    wire is_ack = op == 4'h6 || op == 4'h7 || op == 4'h8 || op == 4'h9 || op == 4'hA || op == 4'hD;
    reg        e2, valid;
    reg [3:0]  plen;
    reg [7:0]  pd [0:11];
    always @(posedge clk) begin
        e2 <= e1 && !rst;
        if (e1) begin
            valid <= mtype == 8'h00 && !(&idle_b) && telid == 4'd0 && tgt_ok && src_ok &&
                     tellen <= (grp ? 4'd11 : 4'd12);
            plen  <= is_ack ? (tellen >= 4'd2 ? tellen - 4'd2 : 4'd0) : tellen;
            for (k = 0; k < 10; k = k + 1) pd[k] <= is_ack ? d[k + 2] : d[k];
            pd[10] <= is_ack ? 8'd0 : d[10];
            pd[11] <= is_ack ? 8'd0 : d[11];
        end
    end

    // ---------------------------------------------------------- E3: the messages
    wire        is_amp  = fb == AMP_FBLOCK;
    wire        is_jlr  = fb == JLR_FBLOCK;
    wire        op_sr   = op == 4'h2 || op == 4'h6;                      // StartResult, StartResultAck
    wire        op_sgs  = op == 4'h0 || op == 4'h2 || op == 4'hC;        // Set, SetGet, Status
    wire        op_res  = op == 4'hC || op == 4'hD;                      // Result, ResultAck
    wire        op_err  = op == 4'hF || op == 4'h9;                      // Error, ErrorAck
    wire [7:0]  sink    = pd[0];
    wire        sink13  = sink >= 8'd1 && sink <= 8'd3;
    wire [1:0]  sidx    = sink[1:0] - 2'd1;                              // sink 1..3 -> stream 0..2
    wire [7:0]  lsink   = pd[1];                                         // SpeakerLevel's sink
    wire        lsink13 = lsink >= 8'd1 && lsink <= 8'd3;
    wire [1:0]  lidx    = lsink[1:0] - 2'd1;
    wire        f_conn  = valid && is_amp && fkt == 12'h111;
    wire        f_sinfo = valid && is_amp && fkt == 12'h110 && op == 4'hC && plen >= 4'd5 && sink13;
    // the channel list: after SinkNr, SrcDelay in a Connect; after SinkNr, DataType,
    // Resolution, AudioChannels, SinkDelay in a SinkInfo
    wire [3:0]  nch     = plen - 4'd2;
    wire [3:0]  n_list  = f_sinfo ? plen - 4'd5 : nch;
    wire [7:0]  cl [0:5];
    assign cl[0] = f_sinfo ? pd[5]  : pd[2];
    assign cl[1] = f_sinfo ? pd[6]  : pd[3];
    assign cl[2] = f_sinfo ? pd[7]  : pd[4];
    assign cl[3] = f_sinfo ? pd[8]  : pd[5];
    assign cl[4] = f_sinfo ? pd[9]  : pd[6];
    assign cl[5] = f_sinfo ? pd[10] : pd[7];
    reg         chan_ok;                                                 // each 0..59, ascending
    always @* begin
        chan_ok = 1'b1;
        for (k = 0; k < 6; k = k + 1)
            if (k < n_list && (cl[k] > 8'd59 || (k > 0 && cl[k] <= cl[k - 1]))) chan_ok = 1'b0;
    end
    // the format: SinkInfo's tuple, or the two a Connect's list is taken for
    wire        p_w3    = f_sinfo && pd[2] == 8'd3;                      // 24 bit
    wire        p_mono  = f_sinfo ? pd[3] == 8'd1 : nch == 4'd2;
    wire        res_ok  = !f_sinfo || pd[2] == 8'd2 || pd[2] == 8'd3;
    wire        chn_ok  = f_sinfo ? (pd[3] == 8'd1 || pd[3] == 8'd2) : (nch == 4'd2 || nch == 4'd4);
    wire [3:0]  need    = p_w3 ? (p_mono ? 4'd3 : 4'd6) : (p_mono ? 4'd2 : 4'd4);
    wire        fmt_ok  = res_ok && chn_ok && chan_ok && (f_sinfo ? (pd[1] == 8'd0 && n_list == need) : 1'b1);
    wire m_conn = f_conn && op_sr && plen >= 4'd4 && fmt_ok && sink13;
    wire m_res  = f_conn && op_res && plen >= 4'd1 && sink13;
    wire m_err  = f_conn && op_err;
    wire m_sinfo = f_sinfo;
    wire m_disc = valid && is_amp && fkt == 12'h112 && op_sr  && plen >= 4'd1 && sink13;
    wire m_mute = valid && is_amp && fkt == 12'h113 && op_sgs && plen >= 4'd2 && sink <= 8'd3;
    wire m_spk  = valid && is_amp && fkt == 12'h46D && op_sgs && plen >= 4'd3 && lsink13;
    wire m_409  = valid && is_jlr && fkt == 12'h409 && op == 4'hC && plen >= 4'd3;
    // the position's bytes: L the first Resolution channels, R the next ones of a stereo
    wire [7:0]  b0 = cl[0] + 8'd1, b1 = cl[1] + 8'd1, b2 = cl[2] + 8'd1,
                b3 = cl[3] + 8'd1, b4 = cl[4] + 8'd1, b5 = cl[5] + 8'd1;
    wire [7:0]  nL2 = p_w3 ? b2 : 8'd0;
    wire [7:0]  nR0 = p_mono ? 8'd0 : (p_w3 ? b3 : b2);
    wire [7:0]  nR1 = p_mono ? 8'd0 : (p_w3 ? b4 : b3);
    wire [7:0]  nR2 = (p_mono || !p_w3) ? 8'd0 : b5;
    // the loudest speaker of a SpeakerLevel: the largest signed byte among pd[2 .. plen-1]
    function [7:0] smax;
        input [7:0] a, b;
        begin smax = ($signed(a) > $signed(b)) ? a : b; end
    endfunction
    wire [7:0] v0 = (plen > 4'd2)  ? pd[2]  : 8'h80;
    wire [7:0] v1 = (plen > 4'd3)  ? pd[3]  : 8'h80;
    wire [7:0] v2 = (plen > 4'd4)  ? pd[4]  : 8'h80;
    wire [7:0] v3 = (plen > 4'd5)  ? pd[5]  : 8'h80;
    wire [7:0] v4 = (plen > 4'd6)  ? pd[6]  : 8'h80;
    wire [7:0] v5 = (plen > 4'd7)  ? pd[7]  : 8'h80;
    wire [7:0] v6 = (plen > 4'd8)  ? pd[8]  : 8'h80;
    wire [7:0] v7 = (plen > 4'd9)  ? pd[9]  : 8'h80;
    wire [7:0] v8 = (plen > 4'd10) ? pd[10] : 8'h80;
    wire [7:0] v9 = (plen > 4'd11) ? pd[11] : 8'h80;
    wire [7:0] m01 = smax(v0, v1), m23 = smax(v2, v3), m45 = smax(v4, v5), m67 = smax(v6, v7), m89 = smax(v8, v9);
    wire [7:0] m03 = smax(m01, m23), m47 = smax(m45, m67);
    wire [7:0] loudest = smax(smax(m03, m47), m89);

    // ---------------------------------------------------------- state
    reg        pos_on [0:2], pos_w3 [0:2], pos_mono [0:2], pos_pend [0:2], confirmed [0:2];
    reg [15:0] pos_dev [0:2];               // the device the position came from
    reg [7:0]  pos_b [0:17];                // stream s: L0 L1 L2 R0 R1 R2 at 6s .. 6s+5, frame bytes
    reg        muted [0:2], have_db [0:2];
    reg [7:0]  lvl_db [0:2];
    reg        have_a, have_n, coef_pend;
    reg [7:0]  raw_a, raw_n;
    reg [7:0]  tag;                         // the coefficient set's tag, one more per set
    // the gain of stream gs (see the header), one lookup in each table
    reg  [1:0]  gs;
    wire        n_first = gs != 2'd0 && have_n;                          // streams 1, 2: 0x409 byte 8 before the volume
    wire        use_db  = have_db[gs] || (!n_first && have_db[0]);
    wire [7:0]  db_sel  = have_db[gs] ? lvl_db[gs] : lvl_db[0];
    wire        use_raw = n_first || have_a;
    wire [7:0]  raw_sel = n_first ? raw_n : raw_a;
    wire [31:0] g_def   = gs == 2'd0 ? GAIN_DEF_MAIN : gs == 2'd1 ? GAIN_DEF_S1 : GAIN_DEF_S2;
    wire [31:0] g_now   = muted[gs] ? 32'd0 : use_db ? gain_db_word(db_sel) : use_raw ? gain_raw_word(raw_sel) : g_def;
    // the next stream whose position goes out
    wire [1:0]  ps = pos_pend[0] ? 2'd0 : pos_pend[1] ? 2'd1 : 2'd2;
    wire [1:0]  pw = !pos_on[ps] ? 2'd0 : pos_w3[ps] ? 2'd3 : 2'd2;      // P[1:0]: off, 16 bit, 24 bit

    // ---------------------------------------------------------- the sequencer, one command a clock
    localparam [2:0] S_IDLE = 3'd0, S_BQ = 3'd1, S_GL = 3'd2, S_GEL = 3'd3, S_GER = 3'd4, S_K = 3'd5;
    localparam [31:0] W_ONE = 32'h1000_0000;                            // 1.0: a straight biquad's b0
    localparam [31:0] W_1MK = 32'h0FF0_0000;                            // 1 - 1/256 (gain_tables.py W_1MK)
    reg [2:0]  st;
    reg [5:0]  idx;                         // coefficient address 0..46
    reg [2:0]  bq5;                         // word within a biquad
    reg [31:0] g_q;
    assign busy = st != S_IDLE || pos_pend[0] || pos_pend[1] || pos_pend[2] || coef_pend;

    always @(posedge clk) begin
        ok <= 1'b0; tel <= 1'b0; hit <= 1'b0;
        if (rst) begin
            for (k = 0; k < 3; k = k + 1) begin
                pos_on[k] <= 1'b0; pos_w3[k] <= 1'b0; pos_mono[k] <= 1'b0; pos_pend[k] <= 1'b0;
                confirmed[k] <= 1'b0; pos_dev[k] <= 16'd0;
                muted[k] <= 1'b0; have_db[k] <= 1'b0; lvl_db[k] <= 8'd0;
            end
            for (k = 0; k < 18; k = k + 1) pos_b[k] <= 8'd0;
            have_a <= 1'b0; have_n <= 1'b0; raw_a <= 8'd0; raw_n <= 8'd0; tag <= 8'd0;
            coef_pend <= 1'b1;              // the first set, with the start-up levels, goes out at once
            st <= S_IDLE; idx <= 6'd0; bq5 <= 3'd0; gs <= 2'd0; g_q <= 32'd0;
            cmd <= 8'd0; p <= 56'd0;
        end else begin
            case (st)
                S_IDLE:
                    if (pos_pend[0] || pos_pend[1] || pos_pend[2]) begin
                        // command 01: P = {00, stream, 0, mono, width}, then L0 L1 L2 R0 R1 R2
                        ok  <= 1'b1;
                        cmd <= 8'h01;
                        p   <= {2'b00, ps, 1'b0, pos_on[ps] & pos_mono[ps], pw,
                                pos_on[ps] ? pos_b[6 * ps + 0] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 1] : 8'd0,
                                pos_on[ps] ? pos_b[6 * ps + 2] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 3] : 8'd0,
                                pos_on[ps] ? pos_b[6 * ps + 4] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 5] : 8'd0};
                        pos_pend[ps] <= 1'b0;
                    end else if (coef_pend) begin
                        coef_pend <= 1'b0;
                        tag <= tag + 8'd1;
                        st <= S_BQ; idx <= 6'd0; bq5 <= 3'd0;
                    end
                S_BQ: begin                 // words 0..39: eight straight biquads
                    ok  <= 1'b1;
                    cmd <= 8'h03;
                    p   <= {2'b00, idx, (bq5 == 3'd0) ? W_ONE : 32'd0, 8'd0, tag};
                    idx <= idx + 6'd1;
                    bq5 <= (bq5 == 3'd4) ? 3'd0 : bq5 + 3'd1;
                    if (idx == 6'd39) begin st <= S_GL; gs <= 2'd0; end
                end
                S_GL: begin                 // look the stream's gain up
                    g_q <= g_now;
                    st  <= S_GEL;
                end
                S_GEL: begin                // words 40 + 2s: L
                    ok  <= 1'b1;
                    cmd <= 8'h03;
                    p   <= {2'b00, idx, g_q, 8'd0, tag};
                    idx <= idx + 6'd1;
                    st  <= S_GER;
                end
                S_GER: begin                // 41 + 2s: R, the same
                    ok  <= 1'b1;
                    cmd <= 8'h03;
                    p   <= {2'b00, idx, g_q, 8'd0, tag};
                    idx <= idx + 6'd1;
                    if (gs == 2'd2) st <= S_K;
                    else begin gs <= gs + 2'd1; st <= S_GL; end
                end
                S_K: begin                  // word 46: 1 - k, and the commit
                    ok  <= 1'b1;
                    cmd <= 8'h03;
                    p   <= {2'b00, idx, W_1MK, 8'h01, tag};
                    st  <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase

            // ---- the telegram just classified (a request set here wins over a clear above)
            if (e2) begin
                tel <= valid;
                hit <= m_conn | m_res | m_err | m_sinfo | m_disc | m_mute | m_spk | m_409;
                if (m_conn || (m_sinfo && fmt_ok)) begin
                    pos_on[sidx]   <= 1'b1;
                    pos_w3[sidx]   <= p_w3;
                    pos_mono[sidx] <= p_mono;
                    pos_b[6 * sidx + 0] <= b0;
                    pos_b[6 * sidx + 1] <= b1;
                    pos_b[6 * sidx + 2] <= nL2;
                    pos_b[6 * sidx + 3] <= nR0;
                    pos_b[6 * sidx + 4] <= nR1;
                    pos_b[6 * sidx + 5] <= nR2;
                    pos_dev[sidx]   <= m_conn ? tgt : src;               // a request's device is its target
                    confirmed[sidx] <= m_sinfo;                          // the device's own word is confirmed
                    pos_pend[sidx]  <= 1'b1;
                end
                if (m_sinfo && !fmt_ok && (!pos_on[sidx] || pos_dev[sidx] == src)) begin
                    pos_on[sidx]   <= 1'b0;                              // nothing is known about the sink any more
                    pos_pend[sidx] <= 1'b1;
                end
                if (m_disc && (!pos_on[sidx] || pos_dev[sidx] == tgt)) begin
                    pos_on[sidx]   <= 1'b0;
                    pos_pend[sidx] <= 1'b1;
                end
                if (m_res && pos_on[sidx] && pos_dev[sidx] == src)
                    confirmed[sidx] <= 1'b1;
                if (m_err)
                    for (k = 0; k < 3; k = k + 1)
                        if (pos_on[k] && !confirmed[k] && pos_dev[k] == src) begin
                            pos_on[k]   <= 1'b0;                         // the device turned the Connect down
                            pos_pend[k] <= 1'b1;
                        end
                if (m_mute) begin
                    for (k = 0; k < 3; k = k + 1)
                        if (sink == 8'd0 || sink == k + 1) muted[k] <= pd[1][0];
                    coef_pend <= 1'b1;
                end
                if (m_spk) begin
                    lvl_db[lidx]  <= loudest;
                    have_db[lidx] <= 1'b1;
                    coef_pend <= 1'b1;
                end
                if (m_409) begin
                    raw_a  <= pd[2];
                    have_a <= 1'b1;
                    if (plen >= 4'd9) begin raw_n <= pd[8]; have_n <= 1'b1; end
                    coef_pend <= 1'b1;
                end
            end
        end
    end
endmodule
