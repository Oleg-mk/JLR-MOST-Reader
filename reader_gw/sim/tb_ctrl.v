// tb_ctrl.v - plays frames.hex into ctrl_decode the way rx_framer delivers a frame (one byte
// write per byte, frame_done after byte 63 with the frame's parity, the block index from byte
// 0's high nibble, the receiver's locked and blk_known from flags.hex) and logs every command
// the decoder sends: "frames_done cmd p" per line into out_cmds.txt. run_ctrl.py compares that
// with ctrl_model.py.
`timescale 1ns/1ps
module tb_ctrl;
    parameter MAXF = 8192;
    parameter GAP = 8;                    // clocks between bytes (the real spacing is ~32)
    reg clk = 0, rst = 1;
    always #5.05 clk = ~clk;             // 99 MHz

    reg [511:0] fr [0:MAXF-1];
    reg [7:0]   fl [0:MAXF-1];           // bit 0 locked, bit 1 blk_known
    integer nfr, i, j, fo;
    integer ncmd = 0, ntel = 0, nhit = 0, nbusy = 0, nframes = 0, ndrop = 0;

    reg        we = 0, fd = 0, fp = 0, bk = 1, lk = 1;
    reg [5:0]  ba = 0;
    reg [7:0]  bd = 0;
    reg [3:0]  bi = 0;
    wire       ok, tel, hit, busy, dropped, par_known;
    wire [7:0] cmd;
    wire [55:0] p;

    ctrl_decode u (.clk(clk), .rst(rst), .byte_we(we), .byte_addr(ba), .byte_data(bd), .frame_done(fd),
                   .frame_par(fp), .blk_idx(bi), .blk_known(bk), .locked(lk), .ok(ok), .cmd(cmd), .p(p),
                   .tel(tel), .hit(hit), .dropped(dropped), .par_known_o(par_known), .busy(busy));

    always @(posedge clk) begin
        if (ok) begin
            ncmd = ncmd + 1;
            $fwrite(fo, "%0d %02x %014x\n", nframes, cmd, p);
        end
        if (tel) ntel = ntel + 1;
        if (hit) nhit = nhit + 1;
        if (dropped) ndrop = ndrop + 1;
        if (fd && bi == 4'd15 && bk && lk && busy) nbusy = nbusy + 1;   // the last block's commands still going
    end

    initial begin
        for (i = 0; i < MAXF; i = i + 1) begin fr[i] = {512{1'bx}}; fl[i] = 8'h03; end
        $readmemh("frames.hex", fr);
        $readmemh("flags.hex", fl);
        nfr = 0;
        while (nfr < MAXF && fr[nfr] !== {512{1'bx}}) nfr = nfr + 1;
        fo = $fopen("out_cmds.txt", "w");
        repeat (4) @(posedge clk);
        rst = 0;
        for (i = 0; i < nfr; i = i + 1) begin
            bi = fr[i][511:508];
            bk = fl[i][1];
            lk = fl[i][0];
            for (j = 0; j < 64; j = j + 1) begin
                repeat (GAP - 1) @(posedge clk);
                @(negedge clk); we = 1; ba = j; bd = fr[i][511 - 8 * j -: 8];
                @(negedge clk); we = 0;
            end
            @(negedge clk); fd = 1; fp = ^fr[i][507:0];          // bits 4..511
            @(negedge clk); fd = 0; nframes = nframes + 1;
        end
        repeat (200) @(posedge clk);
        $display("frames=%0d telegrams=%0d hits=%0d commands=%0d dropped=%0d par_known=%0d busy_at_block_end=%0d",
                 nfr, ntel, nhit, ncmd, ndrop, par_known, nbusy);
        $fclose(fo);
        $finish;
    end
endmodule
