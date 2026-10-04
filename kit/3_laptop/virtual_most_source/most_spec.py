"""
most_spec.py - MOST25 constants taken from the local primary specifications.

Nothing in this file is invented. Every value carries its source. Anything the
specifications do NOT pin down lives in config.py instead, clearly marked.

SOURCES (the MOST specification archive; not in this repository)
  [S1] MOST Specification 10/2006, section 3.1.3.4.2, Table 3-6
       "Structure of a control data frame"
       MOST_2V5_Application.zip -> 1_Core/Specification_2V5-0.zip -> MOSTSpecification.pdf
  [S2] MOST Specification 10/2006, section 3.4.6.2
       "Application Message Service (AMS) and Application Protocols"
  [S3] MOST Specification 10/2006, section 2.3.2.5, Table 2-4 "OPTypes"
  [S4] MOST Book 2 (Grzemba), section 5.1 Table 5.1 (frame map),
       section 5.5.1 Fig 5.11/5.12 (control message)
  [S5] MOST Specification of Physical Layer Rev 1.1 09/2003, section 2.1
       "A MOST frame consists of 512 bits ... Due to biphase mark coding, the
        smallest pulse length is given as: UI = 1/(2B)"
  [S6] FBlock_AudioAmplifier_2V4-3 function catalogue (XML)
  [S7] FBlock_Template_GeneralFBlock_oPhy25_2V5-1 function catalogue (XML)
"""

from fractions import Fraction

# ---------------------------------------------------------------------------
# Frame geometry -- [S4] Table 5.1, [S5] section 2.1
# ---------------------------------------------------------------------------

FRAME_BITS = 512
FRAME_BYTES = 64

# [S4] Table 5.1 "Structure of a MOST25 frame"
#   byte 0  bits 0-3    Preamble
#   byte 0  bits 4-7    Boundary Descriptor
#   byte 1  bits 8-15   Data Byte 0
#   ...
#   byte 60 bits 480-487 Data Byte 59
#   byte 61 bits 488-495 Control frame Byte 0
#   byte 62 bits 496-503 Control frame Byte 1
#   byte 63 bits 504-510 Frame control and status bits
#   byte 63 bit  511     Parity bit
BIT_PREAMBLE = 0
BIT_BD = 4
BIT_DATA0 = 8
BIT_CTRL0 = 488
BIT_CTRL1 = 496
BIT_FRAMECTL = 504
BIT_PARITY = 511

DATA_BYTES = 60          # bytes 1..60 of the frame
BYTE_DATA0 = 1
BYTE_CTRL0 = 61
BYTE_CTRL1 = 62
BYTE_FRAMECTL = 63

PREAMBLE_CELLS = 4       # bits 0..3
PREAMBLE_UI = 8          # 4 cells x 2 UI

# [S4] "The Streaming Channel can thus have a width between 24 and 60 bytes
#       (6 to 15 quadlets) ... The value of the Boundary Descriptor ranges from
#       6 to 15."  Streaming bytes = BD * 4, packet bytes = 60 - BD*4.
BD_MIN = 6
BD_MAX = 15


def streaming_bytes(bd: int) -> int:
    return bd * 4


# ---------------------------------------------------------------------------
# Timing -- [S5] section 2.1
# ---------------------------------------------------------------------------
# "B = 512bit * FS" and "UI = 1/(2B)".  Every bit cell is exactly 2 UI in
# biphase mark, so a frame is exactly 1024 UI regardless of its content.

FS_HZ = 48000
BIT_RATE = FRAME_BITS * FS_HZ          # 24 576 000 bit/s
UI_RATE = 2 * BIT_RATE                 # 49 152 000 UI/s
UI_PER_CELL = 2
UI_PER_FRAME = FRAME_BITS * UI_PER_CELL  # 1024

# Exact, as a Fraction. 1e9 / 49_152_000 = 15625/768 ns.  Held as a rational so
# that timestamps are computed from an integer UI index and never accumulate
# drift, however long the track is.
NS_PER_UI = Fraction(10 ** 9, UI_RATE)
assert NS_PER_UI == Fraction(15625, 768)


def ui_to_ns(ui_index: int) -> Fraction:
    """Exact timestamp of a UI boundary. Integer in, Fraction out."""
    return NS_PER_UI * ui_index


# ---------------------------------------------------------------------------
# Control channel -- [S1] Table 3-6, [S4] section 5.5.1
# ---------------------------------------------------------------------------
# [S4] "it is distributed over 16 frames which are combined into one block.
#       Each frame transports 2 bytes of the channel."
# [S1] "A control data message is 32 bytes long and has the following structure"
#        0-3   Arbitration
#        4-5   Target address
#        6-7   Own address (Source address)
#        8     Message type
#        9-25  Data area            <- 17 bytes, matches [S2]
#        26-27 CRC
#        28-29 Transmission status
#        30-31 Reserved

CTRL_BYTES_PER_FRAME = 2
CTRL_FRAMES_PER_BLOCK = 16
CTRL_BLOCK_BYTES = 32

CB_ARB = 0
CB_TARGET = 4
CB_SOURCE = 6
CB_MSGTYPE = 8
CB_DATA = 9
CB_DATA_LEN = 17
CB_CRC = 26
CB_TXSTATUS = 28
CB_RESERVED = 30

# [S1] / [S4] message types
MSG_NORMAL = 0x00
MSG_REMOTE_READ = 0x01
MSG_REMOTE_WRITE = 0x02
MSG_RES_ALLOCATE = 0x03
MSG_RES_DEALLOCATE = 0x04
MSG_REMOTE_GETSRC = 0x05

# ---------------------------------------------------------------------------
# Telegram inside the 17-byte data area -- [S2] section 3.4.6.2
# ---------------------------------------------------------------------------
#  8b FBlockID | 8b InstID | 12b FktID | 4b OPType | 4b TelID | 4b TelLen |
#  Data0..Data11
TD_FBLOCKID = 0
TD_INSTID = 1
TD_FKT_HI = 2
TD_FKT_LO_OP = 3
TD_TELID_LEN = 4
TD_DATA0 = 5
TD_DATA_MAX = 12

# [S2] TelID table
TELID_SINGLE = 0
TELID_SEG_FIRST = 1
TELID_SEG_MID = 2
TELID_SEG_LAST = 3
TELID_HP_USER = 8
TELID_HP_CTRL = 9

# [S3] Table 2-4.
OP_SET = 0x0
OP_GET = 0x1
OP_SETGET = 0x2
OP_INCREMENT = 0x3
OP_DECREMENT = 0x4
OP_GETINTERFACE = 0x5
OP_STARTRESULTACK = 0x6
OP_ABORTACK = 0x7
OP_STARTACK = 0x8
OP_ERRORACK = 0x9
OP_PROCESSINGACK = 0xA
OP_PROCESSING = 0xB
OP_STATUS = 0xC
OP_RESULTACK = 0xD
OP_INTERFACE = 0xE
OP_ERROR = 0xF

OP_NAMES = {
    0x0: "Set/Start", 0x1: "Get/Abort", 0x2: "SetGet/StartResult",
    0x3: "Increment", 0x4: "Decrement", 0x5: "GetInterface",
    0x6: "StartResultAck", 0x7: "AbortAck", 0x8: "StartAck",
    0x9: "ErrorAck", 0xA: "ProcessingAck", 0xB: "Processing",
    0xC: "Status/Result", 0xD: "ResultAck", 0xE: "Interface", 0xF: "Error",
}

# ---------------------------------------------------------------------------
# AudioAmplifier -- [S6], and Mute from [S7]
# ---------------------------------------------------------------------------
# FBlockID and FunctionIDs read directly out of the function catalogues, not
# recalled. Parameter types likewise.
FBLOCK_AUDIOAMPLIFIER = 0x22       # [S6] <FBlockID>0x22</FBlockID>

# [S6] <FunctionID> / <FunctionName>, with the PNParamType basis data type
FKT_BALANCE = 0x200                # TSByte
FKT_LOUDNESS = 0x201
FKT_BASS = 0x202                   # TSByte
FKT_TREBLE = 0x203                 # TSByte
FKT_FADER = 0x204                  # TSByte
FKT_VOLUME = 0x400                 # TUByte
FKT_EQUALIZER_SETTINGS = 0x461
FKT_SPEAKER_LEVEL = 0x46D

# [S6] AudioAmplifier changelog: "Removed function Mute (0x113), which is now
# referenced from the GeneralFBlock" ... "use Mute property (FktID=0x113) with
# SinkNr=0 instead".
# [S7] 0x113 Mute, Unclassified Property, Length=1:
#        ParamIdx 1 SinkNr  TUByte
#        ParamIdx 2 Status  TBool, BitPos 0 = "Mute On" / "Mute Off"
FKT_MUTE = 0x113

# Basis data type per parameter, from the catalogues. Used to range-check and
# to encode the payload.
PARAM_SBYTE = "TSByte"
PARAM_UBYTE = "TUByte"
PARAM_BOOL = "TBool"

FUNCTION_INFO = {
    FKT_VOLUME:  dict(name="Volume",  ptype=PARAM_UBYTE, source="[S6]"),
    FKT_BASS:    dict(name="Bass",    ptype=PARAM_SBYTE, source="[S6]"),
    FKT_TREBLE:  dict(name="Treble",  ptype=PARAM_SBYTE, source="[S6]"),
    FKT_BALANCE: dict(name="Balance", ptype=PARAM_SBYTE, source="[S6]"),
    FKT_FADER:   dict(name="Fader",   ptype=PARAM_SBYTE, source="[S6]"),
    FKT_MUTE:    dict(name="Mute",    ptype=PARAM_BOOL,  source="[S7]"),
}
