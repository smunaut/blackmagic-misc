#!/usr/bin/env python3

# Copyright (C) 2021 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0

from typing import List

from bmd import SpeedEditorKey, SpeedEditorLed, SpeedEditorJogLed, SpeedEditorJogMode, SpeedEditorHandler, SpeedEditor

class DemoHandler(SpeedEditorHandler):

	JOG = {
		SpeedEditorKey.SHTL:	( SpeedEditorJogLed.SHTL, SpeedEditorJogMode.RELATIVE_2 ),
		SpeedEditorKey.JOG:		( SpeedEditorJogLed.JOG,  SpeedEditorJogMode.ABSOLUTE_CONTINUOUS ),
		SpeedEditorKey.SCRL:	( SpeedEditorJogLed.SCRL, SpeedEditorJogMode.ABSOLUTE_DEADZERO ),
	}

	def __init__(self, se):
		self.se   = se
		self.keys = []
		self.leds = 0
		self.se.set_leds(self.leds)
		self._set_jog_mode_for_key(SpeedEditorKey.SHTL)

	def _set_jog_mode_for_key(self, key : SpeedEditorKey):
		if key not in self.JOG:
			return
		self.se.set_jog_leds( self.JOG[key][0] )
		self.se.set_jog_mode( self.JOG[key][1] )

	def jog(self, mode : SpeedEditorJogMode, value):
		print(f"Jog mode {mode:d} : {value:d}")

	def key(self, keys : List[SpeedEditorKey]):
		# Debug message
		kl = ', '.join([k.name for k in keys])
		if not kl:
			kl = 'None'
		print(f"Keys held: {kl:s}")

		# Find keys being released and toggle led if there is one
		for k in self.keys:
			if k not in keys:
				# Select jog mode
				self._set_jog_mode_for_key(k)

				# Toggle leds
				self.leds ^= getattr(SpeedEditorLed, k.name, 0)
				self.se.set_leds(self.leds)

		self.keys = keys

	def battery(self, charging : bool, level : int):
		print(f"Battery {level:d} %{' and charging' if charging else '':s}")


if __name__ == '__main__':
	se = SpeedEditor()
	se.authenticate()
	se.set_handler(DemoHandler(se))

	while True:
		se.poll()
