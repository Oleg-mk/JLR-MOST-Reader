# virtual_most_source - MOST25 frames, control messages and line coding

The ring the simulations feed the reader with: complete MOST25 frames with
the audio and the control channel in them, turned into the Biphase Mark line.
Copied from MOST25-to-AUDIO at 7ff5d2f; `control.py` and `jlr.py` are new here.

| Module | What it holds |
|---|---|
| `most_spec.py` | every constant the specifications fix - frame and control block layout, bit and UI rates, line coding, FBlock and function IDs - each with its source |
| `config.py` | what the specifications leave open (parity rule, frame control, CRC mode, boundary descriptor, stream offsets, the idle block), as settings; `PREAMBLE_SETS` names the preamble shapes the simulations run with - the placeholder and an S/PDIF-like one with two 3UI runs |
| `frame_builder.py` | complete 64-byte frames: preamble nibble, boundary descriptor, 60 data bytes, control bytes, frame control, parity |
| `control.py` | a telegram into the 32-byte control block and back: the block layout, the 17-byte data area with FBlock, instance, FktID, OPType, TelID and TelLen, segments of a long message, and the block spread over 16 frames as 2 bytes each. Its parser takes a block as a telegram under the rules the MOST25-to-AUDIO host used, so the RTL decoder is checked against it |
| `jlr.py` | the messages of a Jaguar XF X250 as the open projects saw them, each with its source: the nodes, the amplifier's Connect, DisConnect and Mute, SpeakerLevel in dB, the gateway's 0xF0.0x409 levels, a source's Allocate.Result; the stereo's 4 channels and their frame bytes |
| `bmc.py` | Biphase Mark encoding into runs of 1, 2 or 3 UI with the preamble's coding violation, and the decoder back |

Tests (no simulator needed):

```text
python -m virtual_most_source.tests.test_frames
python -m virtual_most_source.tests.test_control
```

`test_frames` checks the specification constants and exact timing (no drift
over an hour of UI), the function IDs against the FBlock catalogue, the frame
layout (sample positions, control bytes, parity catching a flipped bit, refused
settings), and the line coding for every preamble set (only 1/2/3-UI runs,
3-UI runs only inside preambles and every frame opening with one, a decode
back to the same frames, a 4-UI run refused).

`test_control` checks the block's byte positions and the nibble packing of
FktID, OPType, TelID and TelLen, the CRC stand-in, every JLR message through a
block and back, what the parser refuses (system messages, idle blocks, internal
and reserved addresses, a physical source, TelLen over 12 or over 11 to a
group, reserved TelIDs) and what it passes quietly (MOST High Protocol),
segments and their reassembly, blocks laid over frames with idle blocks
between them and read back after the Biphase Mark line, and the JLR facts
(addresses, IDs, the ascending channel list, data byte k at frame byte k+1,
dB bytes in two's complement, the 0x409 byte positions).
