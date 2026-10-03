# reader_hw - the reader's board

One KiCad 10 sheet, `most_reader.kicad_sch`, written by `gen_reader.py`: the generator is the
source, the sheet is its output (`tools/check_sheet.py` fails when they differ). Cut from
MOST25-to-AUDIO's `listener_hw/gen_listener.py` (board v1.5, 7ff5d2f): the references of the
parts that stay are the listener's, so the two boards compare block for block.

```text
python reader_hw/gen_reader.py       the sheet, the project symbol library, the footprints
                                     (FOT, TOSLINK T10, Tang Nano 20K) with the FOT's and the
                                     T10's 3D bodies, the library tables
kicad-cli sch erc ...                0 errors, 0 warnings (check_all.py runs it)
```

## The blocks

| Block | What | From the listener |
|---|---|---|
| 1 Живлення | J4 battery in, F1, D2 SMBJ36A, D1, L2 and the input capacitors; U5 TPS7B8133 always-on 3.3 V (3V3_AON); U6 LMR38020 buck to 5V_SW, enabled by WAKE | unchanged, less U10 and 5V_HOST (no ESP32) |
| 2 Пробудження | U4 74LVC1G123: every RX edge restarts 0.1 s, the ring asleep turns the buck off | unchanged, less U11 (no bypass to watch: the bypass is wire) |
| 3 Кільце | J1 the TE MOST FOT header with its ferrites and Rext; R1, U1 74LVC1G34, R7; U1's output is the ring's TX through R2 and RX_BUF for U4 and U3 | less U2 (the mux), R9, C11 |
| 4 Розв'язка | U3 74LVC1G125 on 3V3_SW: RX_BUF into the FPGA, Ioff when the module is off | less U9 (the retiming flip-flop) |
| 5 FPGA | M1 Tang Nano 20K: RX_IN on pin 27 (IDES8), SPDIF_F on pin 42 (OSER8), 5 V through D3 with C63/C64, 3V3_SW out | 2 signals of the listener's 24 |
| 6 Вихід | J6 PLT133/T10W through R28, fed from 3V3_SW with C31/C32 | the T10 transmitter of block 9, no coax |
| 7 Тестові точки | TP6 3V3_AON, TP7 5V_SW, TP9 GND | unchanged |
| 0 Про плату | the notes: what the board is and what is not on it | new |

The FPGA's two lines keep the listener's pins: the ring comes in on 27 (LCD_B7) through the
IDES8 that was proven there; the S/PDIF leaves on 42 (LCD_R3), where the listener's S/PDIF
was, now through an OSER8 on the same 1.26 ns grid - both on pins whose only other connection
is the module's empty LCD connector. Logs and ring captures go over the module's own USB-UART,
the status over its LEDs.

The TOSLINK transmitter runs from the module's 3.3 V: 20 mA for its LED, nothing a PLL in the
listener's block 9 wanted a regulator of its own for.

## Not on this board, and why

- U2, U9, U11, the Si514 (U7) and its LDO (U8): nothing is put back on the ring. The FOT
  transmitter is driven by U1 alone, as an OS8104 in all-bypass drives it after reset.
- M2 (ESP32), U10 and 5V_HOST: the control channel is read in the FPGA (`reader_gw`).
- U12 DIR9001, U13 SRC4192, X1, U14: no TOSLINK input, no audio in.
- U15 PCM5102A, U16, U17 and the line out: one output, TOSLINK.
- J2, J3 (TDM, I2S, UART headers), J5 (TOSLINK in), J7 (coax).

## The board

`gen_reader_pcb.py`, run with KiCad's own Python, lays the parts out once from the sheet's
netlist: every part's place and the reason in its table (`PLACE`), the outline, four M3
holes, ground pours on both sides, the net classes (Default 0.25 mm, Rail 0.35 mm for the
3.3 V rails, Power 0.6 mm for the battery path and 5 V) and the project's DRC rule
(`most_reader.kicad_dru`, one thermal spoke). From then on `most_reader.kicad_pcb` belongs to
the PCB editor: the user places and routes by hand, and the script refuses to overwrite the
file unless run with `--fresh`, which discards every track. Sheet changes reach the board
through Tools > Update PCB from Schematic.

```text
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" reader_hw\gen_reader_pcb.py [--fresh]
python tools/check_board.py          DRC with the parity check: no violation, no difference
                                     from the sheet; unconnected items fail only once routing
                                     has begun
```

The initial layout, 106 x 90 mm, keeps the listener's geometry where the parts are the same:
J1 on the left edge with its optical face past it, the FOT cluster between J1's pins and M1's
left header (RX_IN enters at M1's pin 8, U3 beside it), M1 upright in the middle with the
USB-C at the top edge, the battery input on the left edge under J1 (fibre and power leave
through one face) and the buck along the bottom. New here: D3 with C63/C64 at M1's 5 V pin,
and J6 on the top edge under M1's SPDIF pin, with R28, C31, C32. The right half is empty where
the ESP32 and the digital audio sat, so the board is for compacting by hand; the module's
3D view shows only its pin headers (soldered in, no sockets).

## Next

The user's placement and routing; then `make_fab.py` in the listener's manner for the
manufacturing package.
