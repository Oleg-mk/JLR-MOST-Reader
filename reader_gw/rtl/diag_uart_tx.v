// diag_uart_tx.v - the log's line to the module's USB-UART bridge: 8N1, bytes back to back.
//
// A byte is a start bit and 8 data bits of DIV clocks each, LSB first, and a stop bit of STOP
// clocks (99 MHz / 33 = 3.000 Mbaud; STOP = DIV is one stop bit). While the FIFO has bytes the
// next start bit follows the stop bit at once, so the line runs at its full rate; the byte to
// send comes off a register (the FIFO's q), never through logic.
module diag_uart_tx #(
    parameter DIV  = 33,                    // clk per bit
    parameter STOP = 33                     // clk of the stop bit
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       avail,                // the FIFO has a byte in data
    input  wire [7:0] data,
    output reg        take,                 // pulse: data is on its way, show the next
    output reg        txd
);
    reg [8:0] sh;                           // data[7:0] and the stop bit; sh[0] goes next
    reg [3:0] n;                            // bit on the line: 0 start, 1..8 data, 9 stop
    reg [7:0] t;                            // clocks left in this bit, less one
    reg       busy;

    always @(posedge clk) begin
        take <= 1'b0;
        if (rst) begin
            busy <= 1'b0; txd <= 1'b1; sh <= 9'h1FF; n <= 4'd0; t <= 8'd0;
        end else if (!busy || (n == 4'd9 && t == 8'd0)) begin
            // idle, or the stop bit is over: the next byte starts at once if there is one
            // (take lags avail by a clock: a byte just taken is not taken twice)
            if (avail && !take) begin
                sh <= {1'b1, data}; txd <= 1'b0; n <= 4'd0; t <= DIV - 1; busy <= 1'b1; take <= 1'b1;
            end else begin
                busy <= 1'b0; txd <= 1'b1;
            end
        end else if (t != 8'd0) begin
            t <= t - 8'd1;
        end else begin
            txd <= sh[0];
            sh  <= {1'b1, sh[8:1]};
            n   <= n + 4'd1;
            t   <= (n == 4'd8) ? STOP - 1 : DIV - 1;
        end
    end
endmodule
