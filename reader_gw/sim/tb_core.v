// tb_core.v - the whole reader from the line: samples.hex (ring_stim.py) through reader_core,
// everything on the way logged for run_e2e.py.
//   out_frames.txt   F n lk bk bi par hex     every frame the receiver completed (n = frames so far)
//   out_cmds.txt     n cmd p                   every command ctrl_decode sent, n = frames done then
//   out_engine.txt   P n pos x18 wid x3 mon x3  a frame collected by amp_out: with these positions
//                    S n lastframe in_w         the engine started on this frame's samples
//                    E n out_w bank             the program ended: outputs and the bank it used
//                    W n bank addr value commit inuse tag   a coefficient word amp_out accepted
//                    K n bank                   the engine's bank switched
//                    BANKERR / OVERRUN
//   out_words.txt    the S/PDIF line, 8 samples a clock, 8 words a line
`timescale 1ns/1ps
module tb_core;
    parameter MAXCLK = 6000000;
    reg clk = 0, rst = 1;
    always #5.05 clk = ~clk;                // 99 MHz

    reg [7:0] mem [0:MAXCLK-1];
    integer nclk, i, j;
    integer ff, fc, fe, fw;
    reg [7:0] samp = 0;
    wire [7:0] word; wire spdif; wire [7:0] status;
    reader_core u (.clk(clk), .rst(rst), .samp(samp), .spdif_word(word), .spdif(spdif), .status(status));

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

    initial begin
        for (i = 0; i < MAXCLK; i = i + 1) mem[i] = 8'hxx;
        $readmemh("samples.hex", mem);
        nclk = 0;
        while (nclk < MAXCLK && mem[nclk] !== 8'hxx) nclk = nclk + 1;
        ff = $fopen("out_frames.txt", "w");
        fc = $fopen("out_cmds.txt", "w");
        fe = $fopen("out_engine.txt", "w");
        fw = $fopen("out_words.txt", "w");
        repeat (4) @(posedge clk);
        rst = 0;
        for (i = 0; i < nclk; i = i + 1) begin
            @(negedge clk) samp = mem[i];
        end
        @(negedge clk) samp = {8{mem[nclk-1][7]}};
        repeat (6000) @(posedge clk);
        if (u.overrun) $fwrite(fe, "OVERRUN\n");
        $display("clocks=%0d frames=%0d errors=%0d telegrams=%0d hits=%0d dropped=%0d commands=%0d starts=%0d ends=%0d status=%b",
                 nclk, nframes, nerr, ntel, nhit, ndrop, ncmd, nstart, nend, status);
        $fclose(ff); $fclose(fc); $fclose(fe); $fclose(fw);
        $finish;
    end
endmodule
