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
//   0x22 0x111 Connect      StartResult(Ack) [SinkNr, SrcDelay, ch...]  sink 1..4 -> stream 0..3;
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
//   0xF0 0x409 (JLR)        Status [kind, ...]                         the whole record (kind 0) alone, a byte
//                                                                      where TelLen covers it: byte 2 the volume
//                                                                      (0..35), byte 9 the navigation, byte 11 the
//                                                                      parking sensors (each the level + 5, 0..25);
//                                                                      kind 1, a Set, a SetGet change nothing
//                                                                      (JLR-HU d6b46e2, AudioControl)
// The sinks, JLR's as mObridge's MOST25 DA guide (pp. 18-19) gives them for Jaguar and Land Rover:
// 1 the main source, 2 phone, navigation and voice, 3 the parking sensors, 4 the chimes.
// Formats (audit R09): from SinkInfo the full tuple, PCM only, 2 or 3 bytes a sample, 1 or 2
// channels, the list exactly Resolution x AudioChannels long. A Connect carries the list alone;
// 4 channels are taken as 16-bit stereo and 2 as 16-bit mono - the formats JLR is on record
// with (STX 5.4.1.1: L-Hi, L-Lo, R-Hi, R-Lo) - and a list of 3 or 6, which could be 24-bit
// stereo or three 16-bit channels, is refused until a SinkInfo names the format. Channels are
// 0..59, ascending; frame byte = channel + 1 (Data Byte k is frame byte k+1).
// A stream's gain, as the host chose it, with stream 2 and 3 added: muted -> 0; its own
// SpeakerLevel (dB); else its own 0x409 level - stream 1 byte 9 (the navigation), stream 2
// byte 11 (the parking sensors); else the volume: SpeakerLevel to sink 1, else 0x409 byte 2 (not for
// stream 3, the chimes: no volume message is on record for them, and a chime must not vanish
// with the volume turned down); else the stream's start-up level (GAIN_DEF_*: the user's
// decision, a third of full volume or less for the main source, their own figures for the
// others), which is also what the first coefficient set after reset carries, so a Connect is
// heard before any level message.
// The dB, volume and level -> word tables are gain_rom.vh, written by sim/gain_tables.py, which
// is also their model. Positions survive a lost lock (audit R06: a gap must not silence the one
// output); a ring restart takes the FPGA's supply with it and so clears everything.
//
// Every change of a stream's position sends command 01 for it; every accepted level or mute
// message rewrites the whole coefficient set as the host did: 49 words, straight biquads,
// k x gain per stream and output, 1 - k, the commit with the last, all carrying the set's tag
// (amp_out switches banks only on a whole set of one tag: audit R03). Commands leave one a
// clock, about 60 clocks for a set - long before the next block can complete, 16 frames later.
// A block goes through five steps, one a clock, so that 99 MHz holds: E1 the fields, E2 the
// telegram, E3 decodes and compares, E4 the message, E5 what it does to each stream. The tables
// take it with e5, 6 clocks after the block's last frame, and its first command leaves 2 later.
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
    output wire        par_sense_o,         // ...and what it is (the log)
    output wire        busy,                // commands pending or going out
    output wire [18:0] dstate               // the log: per stream s at 4s (s 0..2), 14 (s 3): on, confirmed,
                                            // muted, own level; 12 0x409 volume (byte 2) heard, 13 0x409
                                            // navigation (byte 9) heard, 18 0x409 parking (byte 11) heard
);
`include "gain_rom.vh"
    integer k;
    integer kc;                             // the list check's own, so the clocked loops never wake it

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
    assign par_sense_o = par_sense;
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

    // ---------------------------------------------------------- state
    reg        pos_on [0:3], pos_w3 [0:3], pos_mono [0:3], pos_pend [0:3], confirmed [0:3];
    reg [15:0] pos_dev [0:3];               // the device the position came from
    reg [7:0]  pos_b [0:23];                // stream s: L0 L1 L2 R0 R1 R2 at 6s .. 6s+5, frame bytes
    reg        muted [0:3], have_db [0:3];
    reg [7:0]  lvl_db [0:3];
    reg        have_a, have_n, have_p, coef_pend;
    reg [7:0]  raw_a, raw_n, raw_p;
    reg [7:0]  tag;                         // the coefficient set's tag, one more per set

    // E3..E5: the match, the format check and the table write were one clock, 16 ns where the
    // clock gives 10; they are three steps now, each registering what it works out. One block
    // at a time is in them: a block completes at most once a frame (over 500 clocks; a telegram
    // comes once in 16 frames), so the fields (E1) and the payload (E2) hold until the next
    // block's done and the steps after read them as they are. The tables change only with e5
    // (the sequencer only clears pos_pend, and a set here wins), so each step before reads them
    // as the block before left them, as the one clock did, and the sequencer meets a message's
    // whole new state at once, as before.

    // ---------------------------------------------------------- E3: decodes and compares
    wire        is_amp  = fb == AMP_FBLOCK;
    wire        is_jlr  = fb == JLR_FBLOCK;
    wire        op_sr   = op == 4'h2 || op == 4'h6;                      // StartResult, StartResultAck
    wire        op_sgs  = op == 4'h0 || op == 4'h2 || op == 4'hC;        // Set, SetGet, Status
    wire        op_res  = op == 4'hC || op == 4'hD;                      // Result, ResultAck
    wire        op_err  = op == 4'hF || op == 4'h9;                      // Error, ErrorAck
    wire [7:0]  sink    = pd[0];
    wire        sink14  = sink >= 8'd1 && sink <= 8'd4;
    wire [7:0]  lsink   = pd[1];                                         // SpeakerLevel's sink
    wire        lsink14 = lsink >= 8'd1 && lsink <= 8'd4;
    // the channel list: after SinkNr, SrcDelay in a Connect (pd[2..]); after SinkNr, DataType,
    // Resolution, AudioChannels, SinkDelay in a SinkInfo (pd[5..])
    wire [3:0]  nch     = plen - 4'd2;
    wire [3:0]  nls     = plen - 4'd5;
    // the loudest speaker of a SpeakerLevel: the largest signed byte among pd[2 .. plen-1], the
    // same tree of pairs as before, one round a step (E3, E4, E5, and the last into lvl_db)
    function [7:0] smax;
        input [7:0] a, b;
        begin smax = ($signed(a) > $signed(b)) ? a : b; end
    endfunction
    // the first round: a byte past plen counts as 0x80, the smallest; ga = plen > k and
    // gb = plen > k + 1, so gb implies ga, and the gates only pick once the bytes are compared
    function [7:0] pmax;
        input [7:0] a, b;
        input       ga, gb;
        begin pmax = gb ? smax(a, b) : ga ? a : 8'h80; end
    endfunction
    reg        e3;
    reg        c_conn, c_res, c_err, c_sinfo, c_disc, c_mute, c_spk, c_409;
    reg [3:0]  sel, lsel, msel;             // one-hot: the sink's stream, SpeakerLevel's, Mute's
    reg [10:2] hi, nup;                     // pd[j] > 59; pd[j] <= pd[j-1]
    reg [5:0]  in_c, in_s;                  // list entry k is there: k < nch, k < nls
    reg        s_pcm, s_res, s_w3, s_chn, s_mono;
    reg [3:0]  dsrc, dtgt;                  // pos_dev[k] == src, == tgt
    reg [7:0]  m01, m23, m45, m67, m89;
    reg [7:0]  pdp [2:10];                  // pd[j] + 1, a clock ahead of the position's pick: the add
                                            // after the c_sinfo pick was a slowest path (2026-10-04);
                                            // pd holds from E1 to the next telegram, so it is the same
    always @(posedge clk) begin
        e3 <= e2 && !rst;
        if (e2) begin
            // the messages, all but the format of a Connect or a SinkInfo (E4)
            c_conn  <= valid && is_amp && fkt == 12'h111 && op_sr  && plen >= 4'd4 && sink14;
            c_res   <= valid && is_amp && fkt == 12'h111 && op_res && plen >= 4'd1 && sink14;
            c_err   <= valid && is_amp && fkt == 12'h111 && op_err;
            c_sinfo <= valid && is_amp && fkt == 12'h110 && op == 4'hC && plen >= 4'd5 && sink14;
            c_disc  <= valid && is_amp && fkt == 12'h112 && op_sr  && plen >= 4'd1 && sink14;
            c_mute  <= valid && is_amp && fkt == 12'h113 && op_sgs && plen >= 4'd2 && sink <= 8'd4;
            c_spk   <= valid && is_amp && fkt == 12'h46D && op_sgs && plen >= 4'd3 && lsink14;
            c_409   <= valid && is_jlr && fkt == 12'h409 && op == 4'hC && plen >= 4'd3 && pd[0] == 8'd0;
            for (k = 0; k < 4; k = k + 1) begin
                sel[k]  <= (sink[2:0] == k + 1);                         // sink 1..4 -> stream 0..3 (every use has sink14)
                lsel[k] <= (lsink[2:0] == k + 1);                        // SpeakerLevel's (every use has lsink14)
                msel[k] <= (sink == 8'd0 || sink == k + 1);              // Mute's: sink 0 is all
                dsrc[k] <= (pos_dev[k] == src);                          // an answer's device is its source,
                dtgt[k] <= (pos_dev[k] == tgt);                          // a request's its target
            end
            // the channel lists byte by byte: each 0..59, each above the one before
            for (k = 2; k <= 10; k = k + 1) begin
                hi[k]  <= (pd[k] > 8'd59);
                nup[k] <= (pd[k] <= pd[k - 1]);
            end
            for (k = 0; k < 6; k = k + 1) begin
                in_c[k] <= (k < nch);
                in_s[k] <= (k < nls);
            end
            // a SinkInfo's tuple: PCM, 2 or 3 bytes a sample, 1 or 2 channels
            s_pcm  <= pd[1] == 8'd0;
            s_res  <= pd[2] == 8'd2 || pd[2] == 8'd3;
            s_w3   <= pd[2] == 8'd3;                                     // 24 bit
            s_chn  <= pd[3] == 8'd1 || pd[3] == 8'd2;
            s_mono <= pd[3] == 8'd1;
            m01 <= pmax(pd[2],  pd[3],  plen > 4'd2,  plen > 4'd3);
            m23 <= pmax(pd[4],  pd[5],  plen > 4'd4,  plen > 4'd5);
            m45 <= pmax(pd[6],  pd[7],  plen > 4'd6,  plen > 4'd7);
            m67 <= pmax(pd[8],  pd[9],  plen > 4'd8,  plen > 4'd9);
            m89 <= pmax(pd[10], pd[11], plen > 4'd10, plen > 4'd11);
            for (k = 2; k <= 10; k = k + 1) pdp[k] <= pd[k] + 8'd1;
        end
    end

    // ---------------------------------------------------------- E4: the message
    // Both lists are checked and the message takes its own: Connect and SinkInfo have different
    // FktIDs, so a Connect meets the Connect's verdict and a SinkInfo its own, as the one-clock
    // pick of b0..b5 by c_sinfo does.
    reg         chan_c, chan_s;
    always @* begin
        chan_c = 1'b1;
        chan_s = 1'b1;
        for (kc = 0; kc < 6; kc = kc + 1) begin
            if (in_c[kc] && (hi[2 + kc] || (kc > 0 && nup[2 + kc]))) chan_c = 1'b0;
            if (in_s[kc] && (hi[5 + kc] || (kc > 0 && nup[5 + kc]))) chan_s = 1'b0;
        end
    end
    // the format: SinkInfo's tuple, or the two a Connect's list is taken for
    wire [3:0]  need    = s_w3 ? (s_mono ? 4'd3 : 4'd6) : (s_mono ? 4'd2 : 4'd4);
    wire        fmt_c   = (nch == 4'd2 || nch == 4'd4) && chan_c;
    wire        fmt_s   = s_res && s_chn && chan_s && s_pcm && nls == need;
    wire        p_w3    = c_sinfo && s_w3;
    wire        p_mono  = c_sinfo ? s_mono : nch == 4'd2;
    // the position's bytes: L the first Resolution channels, R the next ones of a stereo, each
    // its channel + 1 (pdp, added at E2)
    wire [7:0]  b0 = c_sinfo ? pdp[5]  : pdp[2], b1 = c_sinfo ? pdp[6]  : pdp[3],
                b2 = c_sinfo ? pdp[7]  : pdp[4], b3 = c_sinfo ? pdp[8]  : pdp[5],
                b4 = c_sinfo ? pdp[9]  : pdp[6], b5 = c_sinfo ? pdp[10] : pdp[7];
    reg         e4;
    reg         m_conn, m_res, m_err, m_sok, m_sbad, m_disc, m_mute, m_spk, m_409, hit_m;
    reg         w3_n, mono_n;
    reg  [7:0]  nb [0:5];                   // the new position: L0 L1 L2 R0 R1 R2
    reg  [15:0] dev_n;
    reg  [7:0]  m03, m47, m89_4;
    always @(posedge clk) begin
        e4 <= e3 && !rst;
        if (e3) begin
            m_conn <= c_conn && fmt_c;
            m_sok  <= c_sinfo && fmt_s;                                  // the device's word on its sink
            m_sbad <= c_sinfo && !fmt_s;                                 // any other: nothing is known
            m_res  <= c_res;
            m_err  <= c_err;
            m_disc <= c_disc;
            m_mute <= c_mute;
            m_spk  <= c_spk;
            m_409  <= c_409;
            hit_m  <= (c_conn && fmt_c) || c_res || c_err || c_sinfo || c_disc || c_mute || c_spk || c_409;
            w3_n   <= p_w3;
            mono_n <= p_mono;
            nb[0]  <= b0;
            nb[1]  <= b1;
            nb[2]  <= p_w3 ? b2 : 8'd0;
            nb[3]  <= p_mono ? 8'd0 : (p_w3 ? b3 : b2);
            nb[4]  <= p_mono ? 8'd0 : (p_w3 ? b4 : b3);
            nb[5]  <= (p_mono || !p_w3) ? 8'd0 : b5;
            dev_n  <= c_conn ? tgt : src;                                // a Connect is a request, a SinkInfo an answer
            m03    <= smax(m01, m23);
            m47    <= smax(m45, m67);
            m89_4  <= m89;
        end
    end

    // ---------------------------------------------------------- E5: what it does to each stream
    reg         e5;
    reg  [3:0]  set_s, off_s, cnf_s, mute_s, lvl_s;
    reg         coef_s, a409_s, n409_s, p409_s;
    reg  [7:0]  m07, m89_5;
    always @(posedge clk) begin
        e5 <= e4 && !rst;
        if (e4) begin
            for (k = 0; k < 4; k = k + 1) begin
                set_s[k]  <= (m_conn || m_sok) && sel[k];
                off_s[k]  <= (m_sbad && sel[k] && (!pos_on[k] || dsrc[k])) ||        // nothing known any more
                             (m_disc && sel[k] && (!pos_on[k] || dtgt[k])) ||        // DisConnect from its device
                             (m_err && pos_on[k] && !confirmed[k] && dsrc[k]);       // the device turned it down
                cnf_s[k]  <= m_res && sel[k] && pos_on[k] && dsrc[k];                // the device's Result
                mute_s[k] <= m_mute && msel[k];
                lvl_s[k]  <= m_spk && lsel[k];
            end
            coef_s <= m_mute || m_spk || m_409;
            a409_s <= m_409;
            n409_s <= m_409 && plen >= 4'd10;
            p409_s <= m_409 && plen >= 4'd12;
            m07    <= smax(m03, m47);
            m89_5  <= m89_4;
        end
    end
    wire [7:0]  loudest = smax(m07, m89_5);                             // the last round, straight into lvl_db

    // the gain of stream gs (see the header), one lookup in each table
    reg  [1:0]  gs;
    wire        own     = have_db[gs];
    wire        lvl     = (gs == 2'd1 && have_n) || (gs == 2'd2 && have_p);   // its own 0x409 level: stream 1
                                                                         // byte 9, stream 2 byte 11, before the volume
    wire        vol_ok  = gs != 2'd3;                                    // the chimes never take the volume
    wire        use_db  = own || (!lvl && vol_ok && have_db[0]);
    wire [7:0]  db_sel  = own ? lvl_db[gs] : lvl_db[0];
    wire [7:0]  lvl_sel = gs == 2'd2 ? raw_p : raw_n;
    wire [31:0] g_def   = gs == 2'd0 ? GAIN_DEF_MAIN : gs == 2'd1 ? GAIN_DEF_S1 : gs == 2'd2 ? GAIN_DEF_S2 : GAIN_DEF_S3;
    wire [31:0] g_now   = muted[gs] ? 32'd0 : use_db ? gain_db_word(db_sel) : lvl ? gain_lvl_word(lvl_sel) :
                          (vol_ok && have_a) ? gain_vol_word(raw_a) : g_def;
    // the next stream whose position goes out
    wire [1:0]  ps = pos_pend[0] ? 2'd0 : pos_pend[1] ? 2'd1 : pos_pend[2] ? 2'd2 : 2'd3;
    wire [1:0]  pw = !pos_on[ps] ? 2'd0 : pos_w3[ps] ? 2'd3 : 2'd2;      // P[1:0]: off, 16 bit, 24 bit
    wire        any_pend = pos_pend[0] || pos_pend[1] || pos_pend[2] || pos_pend[3];

    // ---------------------------------------------------------- the sequencer, one command a clock
    localparam [2:0] S_IDLE = 3'd0, S_BQ = 3'd1, S_GL = 3'd2, S_GEL = 3'd3, S_GER = 3'd4, S_K = 3'd5;
    localparam [31:0] W_ONE = 32'h1000_0000;                            // 1.0: a straight biquad's b0
    localparam [31:0] W_1MK = 32'h0FF0_0000;                            // 1 - 1/256 (gain_tables.py W_1MK)
    reg [2:0]  st;
    reg [5:0]  idx;                         // coefficient address 0..48
    reg [2:0]  bq5;                         // word within a biquad
    reg [31:0] g_q;
    assign busy = st != S_IDLE || any_pend || coef_pend;
    assign dstate = {have_p, have_db[3], muted[3], confirmed[3], pos_on[3],
                     have_n, have_a,
                     have_db[2], muted[2], confirmed[2], pos_on[2],
                     have_db[1], muted[1], confirmed[1], pos_on[1],
                     have_db[0], muted[0], confirmed[0], pos_on[0]};

    // Command 01 is put together a clock ahead, in p01_q, from the tables as they are: picked in
    // the clock it left, the stream's six bytes behind the pending bits were clk_s's slowest path
    // (pos_pend -> ps -> pos_b -> p, 6 levels). p01_v says p01_q is the tables' current word: not
    // in the clock after e5 changed them (the request e5 sets then goes out a clock later), not in
    // the clock after the command went out (its pending bit is cleared only then).
    reg  [55:0] p01_q;
    reg  [1:0]  ps_q;
    reg         p01_v;
    wire        fire01 = st == S_IDLE && p01_v;
    always @(posedge clk) begin
        p01_q <= {2'b00, ps, 1'b0, pos_on[ps] & pos_mono[ps], pw,
                  pos_on[ps] ? pos_b[6 * ps + 0] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 1] : 8'd0,
                  pos_on[ps] ? pos_b[6 * ps + 2] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 3] : 8'd0,
                  pos_on[ps] ? pos_b[6 * ps + 4] : 8'd0, pos_on[ps] ? pos_b[6 * ps + 5] : 8'd0};
        ps_q  <= ps;
        p01_v <= any_pend && !e5 && !fire01 && !rst;
    end

    always @(posedge clk) begin
        ok <= 1'b0; tel <= 1'b0; hit <= 1'b0;
        if (rst) begin
            for (k = 0; k < 4; k = k + 1) begin
                pos_on[k] <= 1'b0; pos_w3[k] <= 1'b0; pos_mono[k] <= 1'b0; pos_pend[k] <= 1'b0;
                confirmed[k] <= 1'b0; pos_dev[k] <= 16'd0;
                muted[k] <= 1'b0; have_db[k] <= 1'b0; lvl_db[k] <= 8'd0;
            end
            for (k = 0; k < 24; k = k + 1) pos_b[k] <= 8'd0;
            have_a <= 1'b0; have_n <= 1'b0; have_p <= 1'b0; raw_a <= 8'd0; raw_n <= 8'd0; raw_p <= 8'd0;
            tag <= 8'd0;
            coef_pend <= 1'b1;              // the first set, with the start-up levels, goes out at once
            st <= S_IDLE; idx <= 6'd0; bq5 <= 3'd0; gs <= 2'd0; g_q <= 32'd0;
            cmd <= 8'd0; p <= 56'd0;
        end else begin
            case (st)
                S_IDLE:
                    if (p01_v) begin
                        // command 01: P = {00, stream, 0, mono, width}, then L0 L1 L2 R0 R1 R2
                        ok  <= 1'b1;
                        cmd <= 8'h01;
                        p   <= p01_q;
                        pos_pend[ps_q] <= 1'b0;
                    end else if (any_pend) begin
                        // a position is due and its word is being put together: it goes first
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
                    if (gs == 2'd3) st <= S_K;
                    else begin gs <= gs + 2'd1; st <= S_GL; end
                end
                S_K: begin                  // word 48: 1 - k, and the commit
                    ok  <= 1'b1;
                    cmd <= 8'h03;
                    p   <= {2'b00, idx, W_1MK, 8'h01, tag};
                    st  <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase

            // ---- the block's message, all of it in this one clock (a request set here wins over
            // a clear above); the messages exclude each other, so at most one kind acts
            if (e5) begin
                tel <= valid;
                hit <= hit_m;
                for (k = 0; k < 4; k = k + 1) begin
                    if (set_s[k]) begin
                        pos_on[k]        <= 1'b1;
                        pos_w3[k]        <= w3_n;
                        pos_mono[k]      <= mono_n;
                        pos_b[6 * k + 0] <= nb[0];
                        pos_b[6 * k + 1] <= nb[1];
                        pos_b[6 * k + 2] <= nb[2];
                        pos_b[6 * k + 3] <= nb[3];
                        pos_b[6 * k + 4] <= nb[4];
                        pos_b[6 * k + 5] <= nb[5];
                        pos_dev[k]       <= dev_n;
                        confirmed[k]     <= m_sok;                       // the device's own word is confirmed
                        pos_pend[k]      <= 1'b1;
                    end
                    if (off_s[k]) begin
                        pos_on[k]   <= 1'b0;
                        pos_pend[k] <= 1'b1;
                    end
                    if (cnf_s[k]) confirmed[k] <= 1'b1;
                    if (mute_s[k]) muted[k] <= pd[1][0];
                    if (lvl_s[k]) begin
                        lvl_db[k]  <= loudest;
                        have_db[k] <= 1'b1;
                    end
                end
                if (coef_s) coef_pend <= 1'b1;
                if (a409_s) begin raw_a <= pd[2]; have_a <= 1'b1; end
                if (n409_s) begin raw_n <= pd[9]; have_n <= 1'b1; end
                if (p409_s) begin raw_p <= pd[11]; have_p <= 1'b1; end
            end
        end
    end
endmodule
