// diag_cmd.v - commands from the laptop over the USB-UART bridge (FPGA pin 70): 8N1 in, and
// the listener's 11-byte packet (MOST25-to-AUDIO host_cmd.v):
//
//   A5 5A  C  P0 P1 P2 P3 P4 P5 P6  X        X = XOR of the 10 bytes before it
//
// Only the log's own commands are taken (LOGGING.md); nothing here reaches what the reader
// plays. A packet with a wrong X is dropped; a gap of TOUT clocks between two bytes ends a
// packet, so a lost byte costs that packet only (the listener's parser had no timeout and
// could lose the next one too).
//   10 capture now   P0: 0 runs, 1 frames
//   11 mark          P0, P1: its number, little endian
//   12 fill          P0, P1: seconds of soak-test records (0 stops), P2: their gap in 10 us
//   13 keepalive     P0, P1: DARK ms, P2, P3: COLD ms
module diag_cmd #(
    parameter DIV  = 33,                    // clk per bit
    parameter TOUT = 99000                  // clk between two bytes of a packet at most (1 ms)
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        rxd,
    output reg         ok,                  // pulse: a good packet; cmd and p hold until the next
    output reg  [7:0]  cmd,
    output reg  [55:0] p                    // {P0, P1, .. P6}, P0 in the top byte
);
    // ---------------------------------------------------------------- 8N1 in
    reg [2:0] s;                            // synchroniser; idle high (the pin has a pull-up)
    always @(posedge clk) s <= rst ? 3'b111 : {s[1:0], rxd};
    wire r = s[2];

    reg       busy, bv;
    reg [7:0] tick, sh, bd;
    reg [3:0] bitn;                         // 0 start, 1..8 data, 9 stop
    always @(posedge clk) begin
        bv <= 1'b0;
        if (rst) begin
            busy <= 1'b0; tick <= 8'd0; bitn <= 4'd0; sh <= 8'd0; bd <= 8'd0;
        end else if (!busy) begin
            if (!r) begin busy <= 1'b1; bitn <= 4'd0; tick <= DIV / 2; end   // start edge: to mid-bit
        end else if (tick != 8'd0) begin
            tick <= tick - 8'd1;
        end else begin
            tick <= DIV - 1;
            if (bitn == 4'd0) begin
                if (r) busy <= 1'b0;        // not a start bit after all
            end else if (bitn == 4'd9) begin
                busy <= 1'b0;
                if (r) begin bv <= 1'b1; bd <= sh; end   // a low stop bit drops the byte
            end else begin
                sh <= {r, sh[7:1]};         // LSB first
            end
            bitn <= bitn + 4'd1;
        end
    end

    // ---------------------------------------------------------------- the packet
    reg [3:0]  n;                           // bytes of the packet so far
    reg [7:0]  x, c;
    reg [55:0] ps;
    reg [16:0] gap;                         // clocks since the last byte
    always @(posedge clk) begin
        ok <= 1'b0;
        if (rst) begin
            n <= 4'd0; x <= 8'd0; c <= 8'd0; ps <= 56'd0; cmd <= 8'd0; p <= 56'd0; gap <= 17'd0;
        end else if (bv) begin
            gap <= 17'd0;
            x <= x ^ bd;
            n <= n + 4'd1;
            if (n == 4'd2) c <= bd;
            if (n >= 4'd3 && n <= 4'd9) ps <= {ps[47:0], bd};
            if ((n == 4'd0 && bd != 8'hA5) || (n == 4'd1 && bd != 8'h5A)) begin
                n <= (bd == 8'hA5) ? 4'd1 : 4'd0;           // an A5 here may start the next one
                x <= (bd == 8'hA5) ? 8'hA5 : 8'd0;
            end else if (n == 4'd10) begin
                n <= 4'd0; x <= 8'd0;
                if ((x ^ bd) == 8'd0 && (c == 8'h10 || c == 8'h11 || c == 8'h12 || c == 8'h13)) begin
                    ok <= 1'b1; cmd <= c; p <= ps;
                end
            end
        end else if (n != 4'd0) begin
            if (gap == TOUT[16:0]) begin n <= 4'd0; x <= 8'd0; end
            else gap <= gap + 17'd1;
        end
    end
endmodule
