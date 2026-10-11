# Sources

This page lists where the project's knowledge of JLR's MOST messages, of MOST25 itself and of the parts
comes from. No code or design files were copied from any of these sources. Projects without a
licence were only read.

The MOST specifications are the MOST Cooperation's copyrighted documents and are not in this
repository. The code cites them by section, so a reader with access can check every number.

## JLR's messages on the ring

| Source | What was taken from it |
|---|---|
| Rhys Morgan, **JLR-HU** ([github.com/rhysmorgan134/JLR-HU](https://github.com/rhysmorgan134/JLR-HU)): `findings/most`, `PiMost.ts`, `Globals.ts` | The node addresses: 0x161 gateway, 0x180 audio unit, 0x186 amplifier, 0x16E screen. The amplifier is FBlock 0x22, instance 0x05, sink 1; it gets DisConnect 0x112, then Connect 0x111 about 100 ms later. The gateway's 0xF0.0x409 Status carries the audio level in byte 2, navigation/phone in byte 8 and parking sensors in byte 10. These byte positions come from one parser and still need a recording to confirm them. |
| Rhys Morgan, **SocketMost**, `usb` branch ([github.com/rhysmorgan134/SocketMost](https://github.com/rhysmorgan134/SocketMost)): `JlrAudioControl.ts`, `OS8104A.ts` | Source switching through the gateway, 0xF0.0x405 to 0x408, with AUX as FBlock 0x24. Also that an OS8104 filters control messages by address, which is why this reader decodes them in the FPGA rather than through a MOST chip. |
| mObridge, *MOST25 DA Series Guide*, pp. 18-19 | Which of the amplifier's sinks carries what on Jaguar and Land Rover: phone, navigation and voice on sink 2, the parking sensors on sink 3, the chimes on sink 4 (their mono inputs, by maker). Read from the guide itself. |
| smartgauges, **usb2most** ([github.com/smartgauges/usb2most](https://github.com/smartgauges/usb2most)), GPL-3.0 | A USB-to-MOST adapter with an OS8104A that has been used in a car. Its v3 schematic is the precedent for the optical front end: the TE FOT header, series resistors, Rext. The TE footprint here was drawn from TE's drawing and checked hole for hole against usb2most's. Its published firmware treats 0x22.0x46D SpeakerLevel as the volume on Freelander 2 and the AUD3 amplifiers. |

The open questions about the XF are listed in the [README](README.md#status-what-is-proved-and-what-is-not).
The reader decodes both volume messages, and its log is meant to settle the rest on the first drive.

## MOST25

| Source | Used for |
|---|---|
| MOST Cooperation, *MOST Specification* Rev. 2.5 (10/2006): 3.1.3.4.2 and Table 3-6, 3.4.6.2, 2.3.2.5 and Table 2-4 | the control frame, the application message service, OPTypes |
| MOST Cooperation, *MOST Specification of Physical Layer* Rev. 1.1 (09/2003), 2.1 and the SP tables | the frame, biphase-mark coding, the SP4 limits the end-to-end simulation distorts the line to |
| MOST Cooperation, function catalogues *FBlock AudioAmplifier* 2V4-3 and *GeneralFBlock* | Connect 0x111, DisConnect 0x112, Mute 0x113, SinkInfo 0x110, SpeakerLevel 0x46D |
| A. Grzemba (ed.), *MOST: The Automotive Multimedia Network*: Table 5.1, Fig. 5.11 and 5.12 | the frame's byte map, the control message over 16 frames |
| Oasis SiliconSystems patents by D. Knapp: US 2005/0053179 A1, US 2004/0057542 A1 | the preamble opens with a 3-UI coding violation (the specifications never draw it) |
| Oasis SiliconSystems: EP 1333580 B1, US 6763060 B1 | lock after three valid preambles, unlock after two invalid ones, as the receiver does here |
| IEC 60958-3 | the S/PDIF consumer channel status |

## Parts

| Part | Documents |
|---|---|
| TE 1-1394640-1, MOST pigtail FOT header | TE drawing C-2-2141577-1 rev B; application specification 114-18997 |
| The FOT inside it | Broadcom (Avago) AFBR-1013 data sheet, application note 5344: Rext and the supply filters |
| Everlight PLT237/T10WH, TOSLINK transmitter | DPL-0000256 Rev.1; the T10 housing from PLT133/T10W, DPL-0000049 Rev.5 |
| Sipeed Tang Nano 20K | Sipeed data sheet v1.3 and schematic |
| Gowin GW2AR-18 | data sheet DS226, IBIS models, the vendor's simulation models of OSER8 and IDES8 |
| 74LVC1G34, 74LVC1G125, 74LVC1G123 | Nexperia data sheets |
| TPS7B8133, LMR38020 | TI data sheets (LMR38020: SNVSC40E) |

## The author's earlier project

The reader was cut down from **MOST25-to-AUDIO**, the author's earlier universal MOST25 listener,
which is not public. The receiver, the DSP engine, the S/PDIF coder and the optical front end with
its bypass all come from there, re-checked here. Two steps of `check_all.py` (`tools/crosscheck_most_msg.py`
and `tools/crosscheck_gains.py`) compare this project's decoder and gain tables against that
project's C code. Without it those two steps fail. Everything else runs from this repository.
