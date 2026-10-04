"""MOST25 frames, control messages and Biphase Mark line coding - the simulations' ring.

Complete 64-byte MOST25 frames (frame_builder, config) with control blocks in
them (control: a telegram into its 32 bytes and back; jlr: the Jaguar XF X250
messages the open projects saw), turned into the Biphase Mark line (bmc),
with every constant from the MOST specifications (most_spec, which cites
them). Copied from MOST25-to-AUDIO; control and jlr are new here.
"""
__version__ = "1.1.0"
