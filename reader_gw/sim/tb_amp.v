// tb_amp.v - amp_out (dsp_core and spdif_tx in it) on the frame train, against sim/run_amp.py.
//
// One clock, 99 MHz. The ring is a row of frame edges at the rate FS (delivered to nco_frame
// 160 samples late, as the receiver does), and each frame's 64 bytes (frames.hex) are written
// right after the next frame's edge, as rx_framer completes a frame. Commands (cmds.hex: delay
// in clocks, then C P0..P6) are applied as ctrl_decode's `ok` pulses, one after another.
// Logged for run_amp.py:
//   F n  pos x18 wid x3 mon x3        frame n done, with the positions it was collected with
//   S n  lastframe in_w               the engine started, on this frame's samples
//   E n  out_w bank                   the program ended: outputs and the bank it used
//   W n  bank addr value commit inuse tag   a coefficient word the design accepted (n = starts
//                                    so far; inuse = the engine's bank at that moment)
//   K n  bank                         the engine's bank switched: it holds a whole set now
//   BANKERR / OVERRUN                 the bank changed during a run / a run missed its frame
//   out_words.txt: the S/PDIF line, 8 samples a clock (spdif_word), 8 words a line
`timescale 1ns/1ps
module tb_amp;
    parameter real FS = 48000.0;
    parameter NFRAMES = 400;
    parameter NCMD = 256;
    parameter DELAY = 160;                  // samples from a frame's UI 0 to its fe_valid

    reg clk = 0, rst = 1;
    always #5.05 clk = ~clk;
    reg [28:0] wc = 0;
    always @(posedge clk) wc <= rst ? 29'd0 : wc + 29'd1;
    wire [31:0] now = {wc, 3'b000};

    // ------------------------------------------------ the ring's frame edges
    real        period = 792.0e6 / FS;
    real        t0 = 4000.0;
    integer     ke = 0;                     // edges delivered
    reg         fev = 0, lk = 0;
    reg  [31:0] fet = 0;
    reg         fes = 0;                    // an edge is announced: fev and fet follow next clock
    reg  [31:0] fen = 0;                    // its time, a clock early (fe_next)
    reg  [31:0] edge_t;
    wire        run, tick, fstart, per_ok, rate48;
    wire [2:0]  sub;
    wire [9:0]  phase_n;
    wire [31:0] per, err_last;
    nco_frame u_nco (.clk(clk), .rst(rst), .wc(wc), .locked(lk), .fe_valid(fev), .fe_rise(1'b1), .fe_t(fet), .fe_next(fen),
                     .run(run), .tick(tick), .fstart(fstart), .sub(sub), .phase_n(phase_n), .per(per), .per_ok(per_ok),
                     .rate48(rate48), .err_last(err_last));

    // ---------------------------------------------------------- the design
    reg        cmd_ok = 1'b0; reg [7:0] cmd = 8'd0; reg [55:0] cmd_p = 56'd0;
    reg        bwe = 1'b0, fdone = 1'b0; reg [5:0] ba = 6'd0; reg [7:0] bd = 8'd0;
    wire [7:0] word;
    wire       spdif, overrun;
    amp_out dut (.clk(clk), .rst(rst), .cmd_ok(cmd_ok), .cmd(cmd), .cmd_p(cmd_p),
                 .byte_we(bwe), .byte_addr(ba), .byte_data(bd), .frame_done(fdone),
                 .run(run), .tick(tick), .fstart(fstart), .sub(sub), .phase_n(phase_n), .rate48(rate48),
                 .spdif_word(word), .spdif(spdif), .overrun(overrun));

    // ------------------------------------------------- frames in
    reg [7:0] fb [0:NFRAMES*64-1];
    integer nf = 0, j, flog, slog, fwords;
    reg     burst = 0;
    // edges: one per frame period; after edge k+1 (frame k complete) the frame's bytes go in
    initial begin
        @(negedge rst);
        forever begin
            @(negedge clk);
            // the edge announced in the clock before: the receiver puts a UI 0's time out on
            // fe_next a clock before fe_valid brings it on fe_t
            fev = fes;
            if (fes) begin
                fet = fen; lk = 1;
                ke = ke + 1;
                if (ke >= 2 && nf < NFRAMES) burst = 1;
            end
            fes = 0;
            edge_t = $rtoi(t0 + ke * period + 0.5);
            if ($signed(now - edge_t - (DELAY - 8)) >= 0) begin
                fes = 1; fen = edge_t;
            end
        end
    end
    always @(posedge clk) begin
        if (burst) begin
            burst <= 0;
            repeat (20) @(posedge clk);
            for (j = 0; j < 64; j = j + 1) begin
                bwe <= 1'b1; ba <= j[5:0]; bd <= fb[nf * 64 + j];
                @(posedge clk);
            end
            bwe <= 1'b0;
            fdone <= 1'b1;
            $fwrite(flog, "F %0d", nf);
            for (j = 0; j < 18; j = j + 1) $fwrite(flog, " %0d", dut.pos[j]);
            for (j = 0; j < 3; j = j + 1) $fwrite(flog, " %0d", dut.wid[j]);
            for (j = 0; j < 3; j = j + 1) $fwrite(flog, " %0d", dut.mon[j]);
            $fwrite(flog, "\n");
            @(posedge clk);
            fdone <= 1'b0;
            nf = nf + 1;
        end
    end

    // ------------------------------------------------- commands
    reg [31:0] cd [0:NCMD*9-1];             // delay, C, P0..P6 per command
    integer nc, ci;
    initial begin
        for (ci = 0; ci < NCMD * 9; ci = ci + 1) cd[ci] = 32'hFFFFFFFF;
        $readmemh("cmds.hex", cd);
        @(negedge rst);
        for (nc = 0; nc < NCMD && cd[nc * 9] != 32'hFFFFFFFF; nc = nc + 1) begin
            repeat (cd[nc * 9]) @(posedge clk);
            cmd <= cd[nc * 9 + 1][7:0];
            cmd_p <= {cd[nc*9+2][7:0], cd[nc*9+3][7:0], cd[nc*9+4][7:0], cd[nc*9+5][7:0],
                      cd[nc*9+6][7:0], cd[nc*9+7][7:0], cd[nc*9+8][7:0]};
            cmd_ok <= 1'b1;
            @(posedge clk);
            cmd_ok <= 1'b0;
        end
    end

    // --------------------------------------------------------- engine log
    integer nstart = 0, nend = 0;
    reg run_d = 1'b0, bank_d = 1'b1;
    always @(posedge clk) begin
        if (dut.w_ok)
            $fwrite(slog, "W %0d %0d %0d %0d %0d %0d %0d\n", nstart, dut.bank_w, dut.p_q[53:48],
                    $signed(dut.p_q[47:16]), dut.p_q[8], dut.bank_r, dut.p_q[7:0]);
        if (dut.bank_r !== bank_d) $fwrite(slog, "K %0d %0d\n", nstart, dut.bank_r);
        if (dut.start) begin
            nstart = nstart + 1;
            $fwrite(slog, "S %0d %0d %036h\n", nstart, nf - 1, dut.in_w);
        end
        if (run_d && !dut.running) begin
            nend = nend + 1;
            $fwrite(slog, "E %0d %012h %0d\n", nend, dut.out_w, dut.bank_r);
        end
        if (dut.running && run_d && dut.bank_r !== bank_d) $fwrite(slog, "BANKERR %0d\n", nstart);
        run_d <= dut.running;
        bank_d <= dut.bank_r;
    end

    // --------------------------------------------------------- the line
    integer nw = 0;
    always @(posedge clk) begin
        if (!rst) begin
            $fwrite(fwords, "%02x", word);
            nw = nw + 1;
            if (nw % 8 == 0) $fwrite(fwords, "\n");
        end
    end

    initial begin
        $readmemh("frames.hex", fb);
        flog = $fopen("out_frames.txt", "w");
        slog = $fopen("out_engine.txt", "w");
        fwords = $fopen("out_words.txt", "w");
        repeat (20) @(posedge clk);
        rst = 0;
        wait (nf == NFRAMES);
        repeat (8000) @(posedge clk);
        if (overrun) $fwrite(slog, "OVERRUN\n");
        $display("frames=%0d starts=%0d ends=%0d run=%0d per_ok=%0d rate48=%0d", nf, nstart, nend, run, per_ok, rate48);
        $fclose(flog); $fclose(slog); $fclose(fwords);
        $finish;
    end
endmodule
