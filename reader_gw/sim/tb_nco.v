// tb_nco.v - nco_frame alone: frame edges from fe.txt (one line per frame: the sample time of
// UI 0 and the receiver's lock flag from then on), delivered DELAY samples late as the receiver
// delivers them; every tick and every edge logged for run_nco.py.
//   T clk sub phase_n run     a tick (time = clk x 8 + sub samples)
//   F clk t lk                a frame edge delivered (t its sample time)
//   P clk per per_ok rate48   the period changed
`timescale 1ns/1ps
module tb_nco;
    parameter MAXE = 20000;
    parameter DELAY = 160;                  // samples from UI 0 to fe_valid (the receiver's pipeline)
    reg clk = 0, rst = 1;
    always #5.05 clk = ~clk;

    reg [31:0] et [0:MAXE-1];
    reg [7:0]  el [0:MAXE-1];
    integer ne, i, fo;
    reg [28:0] wc = 0;
    always @(posedge clk) wc <= rst ? 29'd0 : wc + 29'd1;
    wire [31:0] now = {wc, 3'b000};

    reg        fev = 0, lk = 0;
    reg [31:0] fet = 0;
    reg        fes = 0, lkn = 0;            // an edge is announced: fev, fet and lk follow next clock
    reg [31:0] fen = 0;                     // its time, a clock early (fe_next)
    wire       run, tick, per_ok, rate48;
    wire [2:0] sub;
    wire [9:0] phase_n;
    wire [31:0] per, err_last;
    nco_frame u (.clk(clk), .rst(rst), .wc(wc), .locked(lk), .fe_valid(fev), .fe_rise(1'b1), .fe_t(fet), .fe_next(fen),
                 .run(run), .tick(tick), .sub(sub), .phase_n(phase_n), .per(per), .per_ok(per_ok),
                 .rate48(rate48), .err_last(err_last));

    reg [31:0] per_d = 0;
    reg        pok_d = 0;
    always @(posedge clk) begin
        // tick and sub are registered: the tick fell in the word before this clock's
        if (tick) $fwrite(fo, "T %0d %0d %0d %0d\n", wc - 1, sub, phase_n, run);
        if (fev) $fwrite(fo, "F %0d %0d %0d\n", wc, fet, lk);
        if (!rst && (per !== per_d || per_ok !== pok_d) && ^per !== 1'bx)
            $fwrite(fo, "P %0d %0d %0d %0d\n", wc, per, per_ok, rate48);
        if (!rst) begin per_d <= per; pok_d <= per_ok; end
    end

    initial begin
        for (i = 0; i < MAXE; i = i + 1) begin et[i] = 32'hFFFFFFFF; el[i] = 8'd1; end
        $readmemh("fe.hex", et);
        $readmemh("lk.hex", el);
        ne = 0;
        while (ne < MAXE && et[ne] !== 32'hFFFFFFFF) ne = ne + 1;
        fo = $fopen("out_nco.txt", "w");
        repeat (4) @(posedge clk);
        rst = 0;
        i = 0;
        // each edge is announced a clock before it is delivered: the receiver puts a UI 0's time
        // out on fe_next a clock before fe_valid brings it on fe_t (delivery is unchanged)
        while (i < ne || fes) begin
            @(negedge clk);
            fev = fes;
            if (fes) begin fet = fen; lk = lkn; end
            fes = 0;
            if (i < ne && $signed(now - et[i] - (DELAY - 8)) >= 0) begin
                fes = 1; fen = et[i]; lkn = el[i][0];
                i = i + 1;
            end
        end
        @(negedge clk) fev = 0;
        repeat (4000) @(posedge clk);
        $display("edges=%0d run=%0d per=%0d per_ok=%0d rate48=%0d", ne, run, per, per_ok, rate48);
        $fclose(fo);
        $finish;
    end
endmodule
