#!/usr/bin/env python3

# Copyright (C) 2021 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0

import binascii
import enum
import struct
import sys

from typing import List

import hid

# ----------------------------------------------------------------------------
# Enums for keycodes and leds
# ----------------------------------------------------------------------------

# Key Presses are reported in Input Report ID 4 as an array of 6 LE16 keycodes
# that are currently being held down. 0x0000 is no key. No auto-repeat, no hw
# detection of the 'fast double press'. Every time the set of key being held
# down changes, a new report is sent.

class SpeedEditorKey(enum.IntEnum):

	NONE			= 0x00	# /

	SMART_INSRT		= 0x01	# SMART INSRT [CLIP]
	APPND			= 0x02	# APPND [CLIP]
	RIPL_OWR		= 0x03	# RIPL O/WR
	CLOSE_UP		= 0x04	# CLOSE UP [YPOS]
	PLACE_ON_TOP	= 0x05	# PLACE ON TOP
	SRC_OWR			= 0x06	# SRC O/WR

	IN				= 0x07	# IN [CLR]
	OUT				= 0x08	# OUT [CLR]
	TRIM_IN			= 0x09	# TRIM IN
	TRIM_OUT		= 0x0a	# TRIM OUT
	ROLL			= 0x0b	# ROLL [SLIDE]
	SLIP_SRC		= 0x0c	# SLIP SRC
	SLIP_DEST		= 0x0d	# SLIP DEST
	TRANS_DUR		= 0x0e	# TRANS DUR [SET]
	CUT				= 0x0f	# CUT
	DIS				= 0x10	# DIS
	SMTH_CUT		= 0x11	# SMTH CUT

	SOURCE			= 0x1a	# SOURCE
	TIMELINE		= 0x1b	# TIMELINE

	SHTL			= 0x1c	# SHTL
	JOG				= 0x1d	# JOG
	SCRL			= 0x1e	# SCRL

	ESC				= 0x31	# ESC [UNDO]
	SYNC_BIN		= 0x1f	# SYNC BIN
	AUDIO_LEVEL		= 0x2c	# AUDIO LEVEL [MARK]
	FULL_VIEW		= 0x2d	# FULL VIEW [RVW]
	TRANS			= 0x22	# TRANS [TITLE]
	SPLIT			= 0x2f	# SPLIT [MOVE]
	SNAP			= 0x2e	# SNAP [=]
	RIPL_DEL		= 0x2b	# RIPL DEL

	CAM1			= 0x33	# CAM1
	CAM2			= 0x34	# CAM2
	CAM3			= 0x35	# CAM3
	CAM4			= 0x36	# CAM4
	CAM5			= 0x37	# CAM5
	CAM6			= 0x38	# CAM6
	CAM7			= 0x39	# CAM7
	CAM8			= 0x3a	# CAM8
	CAM9			= 0x3b	# CAM9
	LIVE_OWR		= 0x30	# LIVE O/WR [RND]
	VIDEO_ONLY		= 0x25	# VIDEO ONLY
	AUDIO_ONLY		= 0x26	# AUDIO ONLY
	STOP_PLAY		= 0x3c	# STOP/PLAY


# Setting the leds is done with SET_REPORT on Output Report ID 2
# which takes a single LE32 bitfield of the LEDs to enable

class SpeedEditorLed(enum.IntFlag):

	CLOSE_UP	= (1 <<  0)
	CUT			= (1 <<  1)
	DIS			= (1 <<  2)
	SMTH_CUT	= (1 <<  3)
	TRANS		= (1 <<  4)
	SNAP		= (1 <<  5)
	CAM7		= (1 <<  6)
	CAM8		= (1 <<  7)
	CAM9		= (1 <<  8)
	LIVE_OWR	= (1 <<  9)
	CAM4		= (1 << 10)
	CAM5		= (1 << 11)
	CAM6		= (1 << 12)
	VIDEO_ONLY	= (1 << 13)
	CAM1		= (1 << 14)
	CAM2		= (1 << 15)
	CAM3		= (1 << 16)
	AUDIO_ONLY	= (1 << 17)


# The LEDs for the Jog mode button are on a different system ...
# Setting those leds is done with SET_REPORT on Output Report ID 4
# which takes a single 8 bits bitfield of the LEDs to enable

class SpeedEditorJogLed(enum.IntFlag):

	JOG			= (1 <<  0)
	SHTL		= (1 <<  1)
	SCRL		= (1 <<  2)


class SpeedEditorJogMode(enum.IntEnum):

	RELATIVE_0			= 0		# Rela
	ABSOLUTE_CONTINUOUS	= 1		# Send an "absolute" position (based on the position when mode was set) -4096 -> 4096 range ~ half a turn
	RELATIVE_2			= 2		# Same as mode 0 ?
	ABSOLUTE_DEADZERO	= 3		# Same as mode 1 but with a small dead band around zero that maps to 0


# ----------------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------------

	# There is a mutual authentication mechanism where the software and the
	# keyboard authenticate to each other ... without that, the keyboard
	# doesn't send REPORTs :/
	#
	# We don't care about authenticating the keyboard so the implementation
	# here is minimal, just enough to make the keyboard start working


def rol8(v):
	return ((v << 56) | (v >> 8)) & 0xffffffffffffffff


def rol8n(v, n):
	for i in range(n):
		v = rol8(v)
	return v


def bmd_kbd_auth(challenge):

	AUTH_EVEN_TBL = [
		0x3ae1206f97c10bc8,
		0x2a9ab32bebf244c6,
		0x20a6f8b8df9adf0a,
		0xaf80ece52cfc1719,
		0xec2ee2f7414fd151,
		0xb055adfd73344a15,
		0xa63d2e3059001187,
		0x751bf623f42e0dde,
	]
	AUTH_ODD_TBL = [
		0x3e22b34f502e7fde,
		0x24656b981875ab1c,
		0xa17f3456df7bf8c3,
		0x6df72e1941aef698,
		0x72226f011e66ab94,
		0x3831a3c606296b42,
		0xfd7ff81881332c89,
		0x61a3f6474ff236c6,
	]
	MASK = 0xa79a63f585d37bf0

	n = challenge & 7
	v = rol8n(challenge, n)

	if (v & 1) == ((0x78 >> n) & 1):
		k = AUTH_EVEN_TBL[n]
	else:
		v = v ^ rol8(v)
		k = AUTH_ODD_TBL[n]

	return v ^ (rol8(v) & MASK) ^ k


# ----------------------------------------------------------------------------
# Speed Editor "interface"
# ----------------------------------------------------------------------------

class SpeedEditorHandler:

	def jog(self, mode : SpeedEditorJogMode, value):
		pass

	def key(self, keys : List[SpeedEditorKey]):
		"""
		keys Array of SpeedEditorKey representing what's currently being held down
		"""
		pass

	def battery(self, charging : bool, level : int):
		"""
		charging [False/True] Is currently charging
		level    [0-100]      Current charge lvel
		"""
		pass


class SpeedEditor:

	USB_VID			= 0x1edb
	USB_PID			= 0xda0e

	def __init__(self):
		self.dev = hid.Device(self.USB_VID, self.USB_PID)

	def authenticate(self):
		# The authentication is performed over SET_FEATURE/GET_FEATURE on
		# Report ID 6

		# Reset the auth state machine
		self.dev.send_feature_report(b'\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00')

		# Read the keyboard challenge (for keyboard to authenticate app)
		data = self.dev.get_feature_report(6, 10)
		if data[0:2] != b'\x06\x00':
			raise RuntimeError('Failed authentication get_kbd_challenge')
		challenge = int.from_bytes(data[2:], 'little')

		# Send our challenge (to authenticate keyboard)
		# We don't care ... so just send 0x0000000000000000
		self.dev.send_feature_report(b'\x06\x01\x00\x00\x00\x00\x00\x00\x00\x00')

		# Read the keyboard response
		# Again, we don't care, ignore the result
		data = self.dev.get_feature_report(6, 10)
		if data[0:2] != b'\x06\x02':
			raise RuntimeError('Failed authentication get_kbd_response')

		# Compute and send our response
		response = bmd_kbd_auth(challenge)
		self.dev.send_feature_report(b'\x06\x03' + response.to_bytes(8, 'little'))

		# Read the status
		data = self.dev.get_feature_report(6, 10)
		if data[0:2] != b'\x06\x04':
			raise RuntimeError('Failed authentication get_kbd_status')

		# I "think" what gets returned here is the timeout after which auth
		# needs to be done again (returns 600 for me which is plausible)
		return int.from_bytes(data[2:4], 'little')

	def set_handler(self, handler : SpeedEditorHandler):
		self.handler = handler

	def set_leds(self, leds : SpeedEditorLed):
		self.dev.write(struct.pack('<BI', 2, leds))

	def set_jog_leds(self, jogleds : SpeedEditorJogLed):
		self.dev.write(struct.pack('<BB', 4, jogleds))

	def set_jog_mode(self, jogmode : SpeedEditorJogMode, unknown=255):
		self.dev.write(struct.pack('<BBIB', 3, jogmode, 0, unknown))

	def _parse_report_03(self, report):
		# Report ID 03
		# u8   - Report ID
		# u8   - Jog mode
		# le32 - Jog value (signed)
		# u8   - Unknown ?
		rid, jm, jv, ju = struct.unpack('<BBiB', report)
		return self.handler.jog(SpeedEditorJogMode(jm), jv)

	def _parse_report_04(self, report):
		# Report ID 04
		# u8      - Report ID
		# le16[6] - Array of keys held down
		keys = [SpeedEditorKey(k) for k in struct.unpack('<6H', report[1:]) if k != 0]
		return self.handler.key(keys)

	def _parse_report_07(self, report):
		# Report ID 07
		# u8 - Report ID
		# u8 - Charging (1) / Not-charging (0)
		# u8 - Battery level (0-100)
		rid, bs, bl = struct.unpack('<BBB', report)
		return self.handler.battery(bool(bs), bl)

	def poll(self, timeout=None):
		# Get REPORT
		report = self.dev.read(64, timeout=timeout)
		if len(report) == 0:
			return

		# Parse and dispatch to handler
		h = getattr(self, f'_parse_report_{report[0]:02x}', None)
		if h:
			return h(report)
		else:
			print(f"[!] Unhandled report {binascii.b2a_hex(report).decode('utf-8'):s}", file=sys.stderr)
