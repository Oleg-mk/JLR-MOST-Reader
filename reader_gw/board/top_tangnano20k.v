// top_tangnano20k.v - reader_core on a Sipeed Tang Nano 20K (GW2AR-LV18QN88C8/I7), the reader board.
//
// The board wires two of the module's I/O pins and nothing else (reader_hw/most_reader.kicad_sch,
// block 5; the module's header pin in brackets):
//   pin 27 (LCD_B7, header 8)    RX_IN   in   the ring's line after U3, the isolation buffer: IDES8
//   pin 42 (LCD_R3, header 25)   SPDIF_F out  to R28 and J6, the TOSLINK transmitter: OSER8
// On the module both are shared only with its LCD connector, which stays empty. Pin 27 is IOB8[A]
// and its pair IOB8[B] (pin 28) is left free on the board; pin 42 is IOB42[B], whose pair
// IOB42[A] has no pin on the QN88 package (Gowin's pin report). Pin 41 is IOB43[A], another pair.
// A third pin is a supply: pin 16 (LED1, header 7) is held high and is 3V3_SW, the supply of U3
// (microamps) and J6 (PLT133: 3 mA, 10 at most). It sits above WAKE on the board, where the
// module's own 3.3 V (pins 19, 36, at the bottom) had to cross WAKE with a jumper; pin 16 is in
// bank 6 with the LEDs alone, away from the crystal's (7) and the two serdes pins' (5, 4).
// The rest is on the module itself: the 27 MHz crystal (pin 4), five LEDs (pins 15, 17..20,
// active low; their header pins are not wired on this board) and the audio amplifier's enable
// (pin 51, header 29, not wired), held low so the amplifier stays shut down.
// Supply and ground through the header: 5V_SW into pin 21 (through D3), ground on pins 20, 22
// and 35; the module's 3.3 V pins are not used.
//
// Clocks, as MOST25-to-AUDIO's top:
//   27 MHz crystal -> rPLL: CLKOUT = 27 x 44 / 3 = 396 MHz (VCO 792 MHz, ODIV 2;
//   DS226 Table 3-20: VCO 500..1250 MHz, PFD 9 MHz >= 3 MHz)
//   396 MHz -> FCLK of the IDES8 and the OSER8, both DDR: 792 Msps, one sample 1.26 ns
//   396 MHz -> CLKDIV /4 -> 99 MHz: PCLK of both and the whole design (clk_s)
// Word order: IDES8 Q0 is the EARLIEST sample of a word (checked in MOST25-to-AUDIO on Gowin's own
// model); OSER8 sends D0 FIRST (checked here the same way, sim/run_oser.py). reader_core keeps
// bit 0 the earliest on both sides.
module top_tangnano20k (
    input  wire       clk27,         // pin 4   the module's crystal
    input  wire       rx_in,         // pin 27  RX_IN from U3
    output wire       spdif,         // pin 42  SPDIF_F to R28, J6
    output wire       pa_en,         // pin 51  the module's audio amplifier, held shut down
    output wire       sw_vcc,        // pin 16  3V3_SW: U3 and J6 run from it, held high
    output wire [4:0] led_n          // pins 15 17 18 19 20, active low
);
    // ------------------------------------------------------------- clocks
    wire fclk, pll_lock, clk_s;
    rPLL #(
        .FCLKIN("27"), .IDIV_SEL(2), .FBDIV_SEL(43), .ODIV_SEL(2),
        .DYN_IDIV_SEL("false"), .DYN_FBDIV_SEL("false"), .DYN_ODIV_SEL("false"),
        .DYN_SDIV_SEL(2), .CLKFB_SEL("internal"), .CLKOUT_BYPASS("false"),
        .CLKOUTP_BYPASS("false"), .CLKOUTD_BYPASS("false"), .PSDA_SEL("0000"),
        .DUTYDA_SEL("1000"), .DYN_DA_EN("false"), .CLKOUT_FT_DIR(1'b1),
        .CLKOUTP_FT_DIR(1'b1), .CLKOUT_DLY_STEP(0), .CLKOUTP_DLY_STEP(0),
        .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"), .DEVICE("GW2AR-18C")
    ) u_pll (
        .CLKIN(clk27), .CLKFB(1'b0), .RESET(1'b0), .RESET_P(1'b0),
        .FBDSEL(6'd0), .IDSEL(6'd0), .ODSEL(6'd0), .PSDA(4'd0), .DUTYDA(4'd0),
        .FDLY(4'd0), .CLKOUT(fclk), .LOCK(pll_lock), .CLKOUTP(), .CLKOUTD(), .CLKOUTD3()
    );
    CLKDIV #(.DIV_MODE("4"), .GSREN("false")) u_div (
        .HCLKIN(fclk), .RESETN(pll_lock), .CALIB(1'b0), .CLKOUT(clk_s));

    // ------------------------------------------------------------- reset
    // held until the PLL locks, then 2^16 clk_s (0.66 ms) more; registered, and copied by synthesis
    // wherever it would drive more than 64 loads (as in MOST25-to-AUDIO, where one net straight from
    // the counter across the chip was the slowest path)
    reg [16:0] por = 17'd0;
    always @(posedge clk_s or negedge pll_lock)
        if (!pll_lock) por <= 17'd0;
        else if (!por[16]) por <= por + 17'd1;
    reg rst_s /* synthesis syn_maxfan = 64 */;
    initial rst_s = 1'b1;
    always @(posedge clk_s) rst_s <= ~por[16];

    // ---------------------------------------------------------- sampler
    wire [7:0] q;
    IDES8 #(.GSREN("false"), .LSREN("true")) u_ides (
        .D(rx_in), .FCLK(fclk), .PCLK(clk_s), .CALIB(1'b0), .RESET(~pll_lock),
        .Q0(q[0]), .Q1(q[1]), .Q2(q[2]), .Q3(q[3]),
        .Q4(q[4]), .Q5(q[5]), .Q6(q[6]), .Q7(q[7]));
    reg [7:0] samp;
    always @(posedge clk_s) samp <= q;               // bit 0 = earliest

    // -------------------------------------------------------------- core
    wire [7:0] spdif_word, status;
    reader_core u_core (.clk(clk_s), .rst(rst_s), .samp(samp),
                        .spdif_word(spdif_word), .spdif(), .status(status));

    // ---------------------------------------------------------- S/PDIF out
    // one register between the core and the serializer, so the OSER8's inputs come straight off
    // flip-flops wherever placement puts the core; the line leaves one clock later, nothing else
    // changes
    reg [7:0] oword = 8'd0;
    always @(posedge clk_s) oword <= spdif_word;     // bit 0 = earliest
    OSER8 #(.GSREN("false"), .LSREN("true"), .HWL("false"), .TXCLK_POL(1'b0)) u_oser (
        .D0(oword[0]), .D1(oword[1]), .D2(oword[2]), .D3(oword[3]),
        .D4(oword[4]), .D5(oword[5]), .D6(oword[6]), .D7(oword[7]),
        .TX0(1'b0), .TX1(1'b0), .TX2(1'b0), .TX3(1'b0),
        .PCLK(clk_s), .FCLK(fclk), .RESET(~pll_lock), .Q0(spdif), .Q1());

    // the module's own audio amplifier: nothing feeds it on this board
    assign pa_en = 1'b0;
    // U3's and J6's supply (LED1 stays dark: high is off)
    assign sw_vcc = 1'b1;

    // ------------------------------------------------------------- LEDs
    // a pulse lights its LED for 2^23 clk_s (85 ms) so it can be seen
    reg [22:0] hit_t = 23'd0, bad_t = 23'd0;
    always @(posedge clk_s) begin
        hit_t <= status[5] ? {23{1'b1}} : (hit_t != 23'd0 ? hit_t - 23'd1 : 23'd0);
        bad_t <= status[6] ? {23{1'b1}} : (bad_t != 23'd0 ? bad_t - 23'd1 : 23'd0);
    end
    // status = {overrun, dropped, hit, par_known, per_ok, blk_known, run, rx_locked}
    //   LED 0 (pin 15) receiver locked        LED 4 (pin 19) one of our messages decoded (flash)
    //   LED 2 (pin 17) frame train running    LED 5 (pin 20) a block dropped (flash) or an engine overrun (stays)
    //   LED 3 (pin 18) frame parity known     (LED 1, pin 16, is 3V3_SW)
    assign led_n = ~{status[7] | (bad_t != 23'd0), hit_t != 23'd0, status[4], status[1], status[0]};
endmodule
