// tb_core.v - the whole reader from the line: samples.hex (ring_stim.py) through reader_core,
// everything on the way logged for run_e2e.py and run_log.py.
//   out_frames.txt   F n lk bk bi par hex     every frame the receiver completed (n = frames so far)
//   out_cmds.txt     n cmd p                   every command ctrl_decode sent, n = frames done then
//   out_engine.txt   P n pos x18 wid x3 mon x3  a frame collected by amp_out: with these positions
//                    S n lastframe in_w         the engine started on this frame's samples
//                    E n out_w bank             the program ended: outputs and the bank it used
//                    W n bank addr value commit inuse tag   a coefficient word amp_out accepted
//                    K n bank                   the engine's bank switched
//                    BANKERR / OVERRUN
//   out_words.txt    the S/PDIF line, 8 samples a clock, 8 words a line
//   out_uart.txt     c level                   the log's UART line at each change (c = clocks since reset)
//   with +define+LOGTAP, out_tap.txt: what run_log.py's model of the log needs, clock by clock
// The laptop's side: cmds.txt (if present), lines "c b0 b1 .. b10": an 11-byte command packet
// sent on uart_rx from clock c, 8N1 at the log's baud.
// The core's reset is rst or the log's hold, registered, as the board top makes it.
`timescale 1ns/1ps
module tb_core;
    parameter MAXCLK = 6000000;
    parameter TAIL = 6000;                  // clocks after the last sample (the log's FIFO to drain)
    parameter LOG_US_MS = 1000;
    parameter LOG_STAT_LOG2 = 21;
    parameter LOG_CAP_NBW = 4;
    parameter LOG_CAP_BW = 11;
    parameter LOG_CAP_RUN_MS = 10;
    parameter LOG_CAP_FRM_MS = 50;
    parameter LOG_WAKE2_MS = 2000;
    parameter LOG_UNL_HOLD_MS = 1000;
    parameter LOG_UNL_GAP_MS = 10000;
    parameter LOG_POS_WAIT_MS = 5000;
    parameter LOG_POS_GAP_MS = 10000;
    parameter LOG_STOP_US = 1000;
    parameter LOG_ATTACH_MS = 2000;
    parameter LOG_DARK_DEF_MS = 100;
    parameter UDIV = 33;
    reg clk = 0, rst = 1;
    always #5.05 clk = ~clk;                // 99 MHz

    reg [7:0] mem [0:MAXCLK-1];
    integer nclk, i, j;
    integer ff, fc, fe, fw, fu, ft;
    reg [7:0] samp = 0;
    wire [7:0] word; wire spdif; wire [7:0] status;
    wire utx, hold;
    reg  urx = 1'b1;
    reg  rst_c = 1'b1;
    always @(posedge clk) rst_c <= rst | hold;
    reader_core #(.BUILD_ID(32'h5EED_0001), .LOG_US_MS(LOG_US_MS), .LOG_STAT_LOG2(LOG_STAT_LOG2),
                  .LOG_CAP_NBW(LOG_CAP_NBW), .LOG_CAP_BW(LOG_CAP_BW), .LOG_CAP_RUN_MS(LOG_CAP_RUN_MS),
                  .LOG_CAP_FRM_MS(LOG_CAP_FRM_MS), .LOG_WAKE2_MS(LOG_WAKE2_MS), .LOG_UNL_HOLD_MS(LOG_UNL_HOLD_MS),
                  .LOG_UNL_GAP_MS(LOG_UNL_GAP_MS), .LOG_POS_WAIT_MS(LOG_POS_WAIT_MS), .LOG_POS_GAP_MS(LOG_POS_GAP_MS),
                  .LOG_STOP_US(LOG_STOP_US), .LOG_ATTACH_MS(LOG_ATTACH_MS), .LOG_DARK_DEF_MS(LOG_DARK_DEF_MS))
        u (.clk(clk), .rst(rst), .rst_c(rst_c), .samp(samp), .spdif_word(word), .spdif(spdif), .status(status),
           .uart_tx(utx), .uart_rx(urx), .hold(hold));

    // clocks since reset, the time base of out_uart.txt and out_tap.txt
    integer cyc = 0;
    always @(posedge clk) if (!rst) cyc <= cyc + 1;

    // ---------------------------------------------------------- frames and commands
    reg [7:0] fbuf [0:63];
    integer nframes = 0, ncmd = 0, ntel = 0, nhit = 0, ndrop = 0, nerr = 0;
    always @(posedge clk) begin
        if (u.bwe) fbuf[u.ba] <= u.bd;
        if (u.er) nerr = nerr + 1;
        if (u.tel) ntel = ntel + 1;
        if (u.hit) nhit = nhit + 1;
        if (u.dropped) ndrop = ndrop + 1;
        if (u.fd) begin
            $fwrite(ff, "F %0d %0d %0d %0d %0d ", nframes, u.rx_lk, u.bk, u.bi, u.fpar);
            for (j = 0; j < 64; j = j + 1) $fwrite(ff, "%02x", fbuf[j]);
            $fwrite(ff, "\n");
            nframes = nframes + 1;
        end
        if (u.cok) begin
            ncmd = ncmd + 1;
            $fwrite(fc, "%0d %02x %014x\n", nframes, u.ccmd, u.cp);
        end
    end

    // ---------------------------------------------------------- the engine, inside amp_out
    integer nstart = 0, nend = 0, nf_amp = 0;
    reg run_d = 1'b0, bank_d = 1'b1;
    always @(posedge clk) begin
        if (u.u_amp.fd_q) begin
            $fwrite(fe, "P %0d", nf_amp);
            for (j = 0; j < 18; j = j + 1) $fwrite(fe, " %0d", u.u_amp.pos[j]);
            for (j = 0; j < 3; j = j + 1) $fwrite(fe, " %0d", u.u_amp.wid[j]);
            for (j = 0; j < 3; j = j + 1) $fwrite(fe, " %0d", u.u_amp.mon[j]);
            $fwrite(fe, "\n");
            nf_amp = nf_amp + 1;
        end
        if (u.u_amp.w_ok)
            $fwrite(fe, "W %0d %0d %0d %0d %0d %0d %0d\n", nstart, u.u_amp.bank_w, u.u_amp.p_q[53:48],
                    $signed(u.u_amp.p_q[47:16]), u.u_amp.p_q[8], u.u_amp.bank_r, u.u_amp.p_q[7:0]);
        if (u.u_amp.bank_r !== bank_d) $fwrite(fe, "K %0d %0d\n", nstart, u.u_amp.bank_r);
        if (u.u_amp.start) begin
            nstart = nstart + 1;
            $fwrite(fe, "S %0d %0d %036h\n", nstart, nf_amp - 1, u.u_amp.in_w);
        end
        if (run_d && !u.u_amp.running) begin
            nend = nend + 1;
            $fwrite(fe, "E %0d %012h %0d\n", nend, u.u_amp.out_w, u.u_amp.bank_r);
        end
        if (u.u_amp.running && run_d && u.u_amp.bank_r !== bank_d) $fwrite(fe, "BANKERR %0d\n", nstart);
        run_d <= u.u_amp.running;
        bank_d <= u.u_amp.bank_r;
    end

    // ---------------------------------------------------------- the line
    integer nw = 0;
    always @(posedge clk) begin
        if (!rst) begin
            $fwrite(fw, "%02x", word);
            nw = nw + 1;
            if (nw % 8 == 0) $fwrite(fw, "\n");
        end
    end

    // ---------------------------------------------------------- the log's UART line
    reg utx_d = 1'b1;
    always @(posedge clk) if (!rst) begin
        if (utx !== utx_d) $fwrite(fu, "%0d %0d\n", cyc, utx);
        utx_d <= utx;
    end

`ifdef LOGTAP
    // ---------------------------------------------------------- what the log's model needs
    //   F c bi lk bk par pk ps ui bytes   a frame done (raw clock c)
    //   X c d|t|h                         ctrl_decode's dropped / tel / hit pulse
    //   M c cmd p                         the command bus as amp_out registered it
    //   R c len level glitch              a run (rx_runlen)
    //   Y c sym raw level                 a classified run
    //   B c addr data                     a frame byte written
    //   E c                               a frame error;   L c relearn;   N c pin
    //   G c lk bk run pk ps ovr hold      any of these changed
    //   Q c                               the log took a STATUS record (for its intervals)
    //   D c                               the STATUS record went out whole (its intervals start anew)
    //   A c ok bad tag sw                 amp_out: a commit's outcome, a bank switch
    //   I c in_w out_w                    the engine started
    reg [7:0] gst_d = 8'hFF;
    wire [7:0] gst = {1'b0, hold, u.overrun, u.par_sense, u.par_known, u.run, u.bk, u.rx_lk};
    always @(posedge clk) if (!rst) begin
        if (u.fd) begin
            $fwrite(ft, "F %0d %0d %0d %0d %0d %0d %0d %0d ", cyc, u.bi, u.rx_lk, u.bk, u.fpar, u.par_known, u.par_sense, u.ui_q);
            for (j = 0; j < 63; j = j + 1) $fwrite(ft, "%02x", fbuf[j]);
            $fwrite(ft, "%02x\n", (u.bwe && u.ba == 6'd63) ? u.bd : fbuf[63]);
        end
        if (u.dropped) $fwrite(ft, "X %0d d\n", cyc);
        if (u.tel) $fwrite(ft, "X %0d t\n", cyc);
        if (u.hit) $fwrite(ft, "X %0d h\n", cyc);
        if (u.cq_ok) $fwrite(ft, "M %0d %02x %014x\n", cyc, u.cq_cmd, u.cq_p);
        if (u.rv) $fwrite(ft, "R %0d %0d %0d %0d\n", cyc, u.rlen, u.rl, u.gl);
        if (u.sv) $fwrite(ft, "Y %0d %0d %0d %0d\n", cyc, u.sym, u.sraw, u.sl);
        if (u.bwe) $fwrite(ft, "B %0d %0d %0d %0d\n", cyc, u.ba, u.bd, u.bi);
        if (u.er) $fwrite(ft, "E %0d\n", cyc);
        if (u.relearn) $fwrite(ft, "L %0d\n", cyc);
        if (u.pin) $fwrite(ft, "N %0d\n", cyc);
        if (gst !== gst_d) $fwrite(ft, "G %0d %0d %0d %0d %0d %0d %0d %0d\n", cyc, u.rx_lk, u.bk, u.run, u.par_known,
                                   u.par_sense, u.overrun, hold);
        gst_d <= gst;
        if (u.u_log.st_load) $fwrite(ft, "Q %0d\n", cyc);
        if (u.u_log.done[1]) $fwrite(ft, "D %0d\n", cyc);
        if (u.commit_ok || u.commit_bad || u.bank_sw)
            $fwrite(ft, "A %0d %0d %0d %0d %0d\n", cyc, u.commit_ok, u.commit_bad, u.commit_tag, u.bank_sw);
        if (u.estart) $fwrite(ft, "I %0d %036h %012h\n", cyc, u.in_w, u.out_w);
    end
`endif

    // ---------------------------------------------------------- the laptop: command packets
    integer fcm, rc, ccyc, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, k;
    reg [7:0] pk [0:10];
    task send_byte(input [7:0] v);
        integer bb;
        begin
            urx = 1'b0; repeat (UDIV) @(posedge clk);
            for (bb = 0; bb < 8; bb = bb + 1) begin urx = v[bb]; repeat (UDIV) @(posedge clk); end
            urx = 1'b1; repeat (UDIV) @(posedge clk);
        end
    endtask
    initial begin
        fcm = $fopen("cmds.txt", "r");
        if (fcm != 0) begin
            while (!$feof(fcm)) begin
                rc = $fscanf(fcm, "%d %h %h %h %h %h %h %h %h %h %h %h\n", ccyc, b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, b10);
                if (rc == 12) begin
                    pk[0] = b0; pk[1] = b1; pk[2] = b2; pk[3] = b3; pk[4] = b4; pk[5] = b5;
                    pk[6] = b6; pk[7] = b7; pk[8] = b8; pk[9] = b9; pk[10] = b10;
                    while (cyc < ccyc) @(posedge clk);
                    for (k = 0; k < 11; k = k + 1) send_byte(pk[k]);
                end
            end
            $fclose(fcm);
        end
    end

    initial begin
        for (i = 0; i < MAXCLK; i = i + 1) mem[i] = 8'hxx;
        $readmemh("samples.hex", mem);
        nclk = 0;
        while (nclk < MAXCLK && mem[nclk] !== 8'hxx) nclk = nclk + 1;
        ff = $fopen("out_frames.txt", "w");
        fc = $fopen("out_cmds.txt", "w");
        fe = $fopen("out_engine.txt", "w");
        fw = $fopen("out_words.txt", "w");
        fu = $fopen("out_uart.txt", "w");
`ifdef LOGTAP
        ft = $fopen("out_tap.txt", "w");
`endif
        repeat (4) @(posedge clk);
        rst = 0;
        for (i = 0; i < nclk; i = i + 1) begin
            @(negedge clk) samp = mem[i];
        end
        @(negedge clk) samp = {8{mem[nclk-1][7]}};
        repeat (TAIL) @(posedge clk);
        if (u.overrun) $fwrite(fe, "OVERRUN\n");
        $display("clocks=%0d frames=%0d errors=%0d telegrams=%0d hits=%0d dropped=%0d commands=%0d starts=%0d ends=%0d status=%b",
                 nclk, nframes, nerr, ntel, nhit, ndrop, ncmd, nstart, nend, status);
        $fwrite(fu, "%0d end\n", cyc);
        $fclose(ff); $fclose(fc); $fclose(fe); $fclose(fw); $fclose(fu);
`ifdef LOGTAP
        $fclose(ft);
`endif
        $finish;
    end
endmodule
