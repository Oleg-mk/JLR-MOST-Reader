// diag_fifo.v - the log's output FIFO: bytes in at up to one a clock, out to the UART.
//
// 2^AW bytes in block RAM (AW = 12: 4 KB, two BSRAM blocks), first word fall-through: the
// oldest byte waits in q (avail) until the reader takes it (take), and the next one is there a
// clock later. The RAM is written and read through registers only; free counts what the RAM
// can still take, so a writer that checks it before a record never overruns.
module diag_fifo #(
    parameter AW = 12
) (
    input  wire          clk,
    input  wire          rst,
    input  wire          we,
    input  wire [7:0]    wd,
    output reg  [AW:0]   free,              // bytes the RAM can still take (registered)
    output reg           avail,             // q holds the oldest byte
    output reg  [7:0]    q,
    input  wire          take               // pulse while avail: q is used, show the next
);
    reg [7:0]  mem [0:(1 << AW) - 1];
    reg [AW:0] wp, rp;
    wire       empty = (wp == rp);
    wire       fetch = !rst && !empty && (!avail || take);

    always @(posedge clk) if (we) mem[wp[AW-1:0]] <= wd;
    always @(posedge clk) if (fetch) q <= mem[rp[AW-1:0]];

    always @(posedge clk) begin
        if (rst) begin
            wp <= 0; rp <= 0; avail <= 1'b0; free <= {1'b1, {AW{1'b0}}};
        end else begin
            if (we) wp <= wp + 1'b1;
            if (fetch) rp <= rp + 1'b1;
            if (fetch) avail <= 1'b1;
            else if (take) avail <= 1'b0;
            // an up/down count: one less for a byte written, one more for a byte fetched
            if (we && !fetch) free <= free - 1'b1;
            else if (fetch && !we) free <= free + 1'b1;
        end
    end
endmodule
