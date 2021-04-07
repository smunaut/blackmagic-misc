#!/usr/bin/env python3

"""
Quick & Dirty timelapse generator for BRAW files

Copyright (C) 2021 Sylvain Munaut <tnt@246tNt.com>
SPDX-License-Identifier: Apache-2.0
"""

import functools
import mmap
import os
import struct
import sys

from collections import namedtuple


# ----------------------------------------------------------------------------
# Metadata block parsing
# ----------------------------------------------------------------------------

class Atom:

	__atoms = {}

	def __init__(self, data):
		self.data = data

	def serialize(self):
		return self.data

	def print(self, lvl=0):
		print("%6d %08x %s-%s" % (len(self.data), self.AID, lvl*' |', bytes(self.data[4:8]).decode('utf8')))

	@classmethod
	def all_atoms(cls):
		return set(cls.__subclasses__()).union(
				[s for c in cls.__subclasses__() for s in c.all_atoms()]
			)

	@classmethod
	def for_aid(cls, aid, fallback=False):
		# Maybe already there
		if aid in cls.__atoms:
			return cls.__atoms[aid]

		# Update
		for ac in cls.all_atoms():
			if hasattr(ac, 'AID'):
				cls.__atoms[ac.AID] = ac

		# Fallback
		if fallback:
			if aid not in cls.__atoms:
				return LeafAtom

		# Get it (or error out if not found)
		return cls.__atoms[aid]

	@classmethod
	def for_buf(cls, buf):
		if len(buf) < 8:
			raise ValueError('Buffer too small for ATOM')
		alen, aid = struct.unpack('>II', buf[0:8])
		acls = cls.for_aid(aid)
		return acls(buf[0:alen])


class ContainerAtom(Atom):

	def __init__(self, data):
		# Super call
		super().__init__(data)

		# Children
		self.children = []

		# Parse atoms inside it
		o = 8
		l = len(data)

		while o <= (l-8):
			# Get length and atom
			alen, aid = struct.unpack('>II', data[o:o+8])

			# Build atom
			acls = Atom.for_aid(aid)
			ainst = acls(data[o:o+alen])

			# Add it
			self.children.append(ainst)

			# Next
			o += alen

		# Error ?
		if o != l:
			raise ValueError('Data left over while parsing children list')

	def __getitem__(self, key):
		# Split into components
		if '/' in key:
			key, skey = key.split('/', 1)
		else:
			skey = None

		# Index
		if ':' in key:
			key, idx = key.split(':')
			idx = int(idx)
		else:
			idx = None

		# Check
		if len(key) != 4:
			raise KeyError('Invalid key %r' % key)

		key = struct.unpack('>I', bytes(key, 'utf8'))[0]

		# Find all matching children
		m = [c for c in self.children if c.AID == key]

		# Index handling
		if len(m) == 0:
			raise KeyError('No such key %08x' % key)
		elif (len(m) > 1) and (idx is None):
			raise KeyError('Multiple key %08x and no index provided' % key)
		elif (idx is not None) and (len(m) <= idx):
			raise KeyError('Invalid index %d for key %08x' % (idx, key))

		# Result
		rv = m[idx or 0]
		return rv[skey] if skey else rv

	def __contains__(self, key):
		# Key conversion/validation
		if len(key) != 4:
			return False
		key = struct.unpack('>I', bytes(key, 'utf8'))[0]

		# Find all matching children
		m = [c for c in self.children if c.AID == key]

		# Any found ?
		return len(m) > 0

	def serialize(self):
		cb = b''.join([c.serialize() for c in self.children])
		return struct.pack('>II', 8 + len(cb), self.AID) + cb

	def print(self, lvl=0):
		print("%6d %08x %s-%s" % (len(self.data), self.AID, lvl*' |', bytes(self.data[4:8]).decode('utf8')))
		for c in self.children:
			c.print(lvl+1)


class LeafAtom(Atom):
	pass


class DecodedLeafAtom(Atom):

	H = None
	L = None

	H_s = None
	H_t = None
	L_s = None
	L_t = None

	def __init__(self, data):
		# Super call
		super().__init__(data)

		# Base offset
		ofs = 8

		# Decode header
		if self.H is not None:
			self.hdr = self.hdr_tuple()(*self.hdr_struct().unpack_from(data, offset=ofs))
			ofs += self.hdr_struct().size
		else:
			self.hdr = None

		# Decode list
		if self.L is not None:
			self.lst = []
			while ofs < len(data):
				e = self.lst_tuple()(*self.lst_struct().unpack_from(data, offset=ofs))
				ofs += self.lst_struct().size
				self.lst.append(e)
		else:
			self.lst = None

	def update(self, **kwargs):
		self.hdr = self.hdr._replace(**kwargs)

	def serialize(self):
		# Serialize header
		if self.H is not None:
			hs = self.hdr_struct().pack(*self.hdr)
		else:
			hs = b''

		# Serialize list
		if self.L is not None:
			ls = b''.join([self.lst_struct().pack(*e) for e in self.lst])
		else:
			ls = b''

		# Final
		return struct.pack('>II', 8 + len(hs) + len(ls), self.AID) + hs + ls

	@classmethod
	@functools.lru_cache
	def hdr_struct(cls):
		return struct.Struct('>' + ''.join([x[1] for x in cls.H])) \
			if (cls.H is not None) else None

	@classmethod
	@functools.lru_cache
	def hdr_tuple(cls):
		return namedtuple(
			cls.__name__ + 'hdr',
			[x[0] for x in cls.H]
		) if (cls.H is not None) else None

	@classmethod
	@functools.lru_cache
	def lst_struct(cls):
		return struct.Struct('>' + ''.join([x[1] for x in cls.L])) \
			if (cls is not None) else None

	@classmethod
	@functools.lru_cache
	def lst_tuple(cls):
		return namedtuple(
			cls.__name__ + 'lst',
			[x[0] for x in cls.L]
		) if (cls.L is not None) else None



class AtomMOOV(ContainerAtom):
	AID = 0x6d6f6f76	# 'moov'


class AtomMVHD(DecodedLeafAtom):
	AID = 0x6d766864	# 'mvhd'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'creation_time',		'I' ),
		( 'modification_time',	'I' ),
		( 'timescale',			'I' ),
		( 'duration',			'I' ),
		( 'preferred_rate',		'I' ),
		( 'preferred_volume',	'H' ),
		( 'reserved',			'10s' ),
		( 'matrix',				'36s' ),
		( 'preview_time',		'I' ),
		( 'preview_duration',	'I' ),
		( 'poster_time',		'I' ),
		( 'selection_time',		'I' ),
		( 'selection_duration',	'I' ),
		( 'current_time',		'I' ),
		( 'next_track_id',		'I' ),
	]


class AtomTRAK(ContainerAtom):
	AID = 0x7472616b	# 'trak'


class AtomTKHD(DecodedLeafAtom):
	AID = 0x746b6864	# 'tkhd'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'creation_time',		'I' ),
		( 'modification_time',	'I' ),
		( 'track_id',			'I' ),
		( 'reserved1',			'4s' ),
		( 'duration',			'I' ),
		( 'reserved2',			'8s' ),
		( 'layer',				'H' ),
		( 'alternate_group',	'H' ),
		( 'volume',				'H' ),
		( 'reserved3',			'H' ),
		( 'matrix',				'36s' ),
		( 'track_width',		'I' ),
		( 'track_height',		'I' ),
	]


class AtomEDTS(ContainerAtom):
	AID = 0x65647473	# 'edts'


class AtomELST(DecodedLeafAtom):
	AID = 0x656c7374	# 'elst'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'num_entries',		'I' ),
	]
	L = [
		( 'track_duration',		'I' ),
		( 'media_time',			'I' ),
		( 'media_rate',			'I' ),
	]


class AtomTREF(ContainerAtom):
	AID = 0x74726566	# 'tref'


class AtomTMCD(LeafAtom):
	AID = 0x746d6364	# 'tmcd'


class AtomMDIA(ContainerAtom):
	AID = 0x6d646961	# 'mdia'


class AtomMDHD(DecodedLeafAtom):
	AID = 0x6d646864	# 'mdhd'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'creation_time',		'I' ),
		( 'modification_time',	'I' ),
		( 'timescale',			'I' ),
		( 'duration',			'I' ),
		( 'language',			'H' ),
		( 'quality',			'H' ),
	]


class AtomHDLR(LeafAtom):
	AID = 0x68646c72	# 'hdlr'


class AtomMINF(ContainerAtom):
	AID = 0x6d696e66	# 'minf'


class AtomVMHD(LeafAtom):
	AID = 0x766d6864	# 'vmhd'


class AtomSMHD(LeafAtom):
	AID = 0x736d6864	# 'smhd'


class AtomGMHD(ContainerAtom):
	AID = 0x676d6864	# 'gmhd'


class AtomGMIN(LeafAtom):
	AID = 0x676d696e	# 'gmin'


class AtomTEXT(LeafAtom):
	AID = 0x74657374	# 'text'


class AtomDINF(ContainerAtom):
	AID = 0x64696e66	# 'dinf'


class AtomDREF(LeafAtom):
	AID = 0x64726566	# 'dref'


class AtomSTBL(ContainerAtom):
	AID = 0x7374626c	# 'stbl'


class AtomSTSD(LeafAtom):
	AID = 0x73747364	# 'stsd'


class AtomSKIP(LeafAtom):
	AID = 0x736b6970	# 'skip'


class AtomSTTS(DecodedLeafAtom):
	AID = 0x73747473	# 'stts'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'num_entries',		'I' ),
	]
	L = [
		( 'sample_count',		'I' ),
		( 'sample_duration',	'I' ),
	]


class AtomSTSC(DecodedLeafAtom):
	AID = 0x73747363	# 'stsc'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'num_entries',		'I' ),
	]
	L = [
		( 'first_chunk',		'I' ),
		( 'samples_per_chunk',	'I' ),
		( 'sample_description_id', 'I' ),
	]


class AtomSTSZ(DecodedLeafAtom):
	AID = 0x7374737a	# 'stsz'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'sample_size',		'I' ),
		( 'num_entries',		'I' ),
	]
	L = [
		( 'size',				'I' ),
	]


class AtomCO64(DecodedLeafAtom):
	AID = 0x636f3634	# 'co64'
	H = [
		( 'version',			'B' ),
		( 'flags',				'3s' ),
		( 'num_entries',		'I' ),
	]
	L = [
		( 'offset',				'Q' ),
	]


class AtomMETA(ContainerAtom):
	AID = 0x6d657461	# 'meta'


class AtomKEYS(LeafAtom):
	AID = 0x6b657973	# 'keys'


class AtomILST(LeafAtom):
	AID = 0x696c7374	# 'ilst'


# ----------------------------------------------------------------------------
# BRAW file reader
# ----------------------------------------------------------------------------

class BrawReader:

	K_WIDE = 0x77696465		# 'wide'
	K_MDAT = 0x6d646174		# 'mdat'

	def __init__(self, filename):
		self.fileno = os.open(filename, os.O_RDONLY)
		self.mm = mmap.mmap(self.fileno, 0, access=mmap.ACCESS_READ)
		self.mv = memoryview(self.mm)

#	def __del__(self):
#		self.mm.close()
#		os.close(self.fileno)

	def parse(self):
		# MetaData pointer
		mp = struct.unpack('>IIII', self.mv[0:16])

		if (mp[0:2] == (8, self.K_WIDE)) and (mp[3] == self.K_MDAT):
			# Format 1 -> be32:8, be32:'wide', be32:(ptr-8), be32:'mdat'
			self.md_ofs = mp[2] + 8

		elif mp[0:2] == (1, self.K_MDAT):
			# Format 2 -> be32:1, be32:'mdat', be64:ptr
			self.md_ofs = (mp[2] << 32) | mp[3]

		else:
			raise RuntimeError('Unknown metadata pointer format')

		# MetaData block
		self.md_blk  = self.mv[self.md_ofs:self.mm.size()]
		self.md_atom = Atom.for_buf(self.md_blk)

		# Identify tracks
		idx = 0
		self.trk_vid_idx = -1
		self.trk_aud_idx = -1
		self.trk_tim_idx = -1

		for c in self.md_atom.children:
			# Only parse tracks
			if c.AID != AtomTRAK.AID:
				continue

			# Get media info
			try:
				minf = c['mdia/minf']
			except:
				idx += 1
				continue

			if 'vmhd' in minf:
				if self.trk_vid_idx == -1:
					self.trk_vid_idx = idx
				else:
					raise RuntimeError('Multiple video tracks')

			elif 'smhd' in minf:
				if self.trk_aud_idx == -1:
					self.trk_aud_idx = idx
				else:
					raise RuntimeError('Multiple audio tracks')

			elif 'gmhd' in minf:
				if self.trk_tim_idx == -1:
					self.trk_tim_idx = idx
				else:
					raise RuntimeError('Multiple timecode tracks')

			idx += 1

		if self.trk_vid_idx == -1:
			raise RuntimeError('Missing video track')

		if self.trk_tim_idx == -1:
			raise RuntimeError('Missing timecode track')

		# Video frames
		v_stsz = self.md_atom['trak:%d/mdia/minf/stbl/stsz' % self.trk_vid_idx]
		v_co64 = self.md_atom['trak:%d/mdia/minf/stbl/co64' % self.trk_vid_idx]

		if v_stsz.hdr.num_entries != v_co64.hdr.num_entries:
			raise ValueError('Inconsistent number of entried in STSZ & CO64')

		self.frames = []

		for i in range(v_stsz.hdr.num_entries):
			fs = v_stsz.lst[i].size
			fo = v_co64.lst[i].offset
			self.frames.append( self.mv[fo:fo+fs] )


# ----------------------------------------------------------------------------
# BRAW Timelapse generator
# ----------------------------------------------------------------------------

class BrawTimelapser:

	def __init__(self, src):
		self.src = src

	def build_metadata(self):
		# Clone original meta data (so we can edit it)
		md_atom = Atom.for_buf(self.src.md_blk)

		# Original / New frame count
		nf_org = len(self.src.frames)
		nf_new = len(self.frames_offset)

		# Tracks
		v_trak = md_atom['trak:%d' % self.src.trk_vid_idx]
		t_trak = md_atom['trak:%d' % self.src.trk_tim_idx]

		# Remove audio track
		if self.src.trk_aud_idx != -1:
			md_atom.children.remove( md_atom['trak:%d' % self.src.trk_aud_idx] )

		# 'mvhd' duration
		md_atom['mvhd'].update(duration=nf_new)

		# 'tkhd' duration
		v_trak['tkhd'].update(duration=nf_new)
		t_trak['tkhd'].update(duration=nf_new)

		# 'elst' duration
		v_trak['edts/elst'].lst[0] = v_trak['edts/elst'].lst[0]._replace(track_duration=nf_new)
		t_trak['edts/elst'].lst[0] = t_trak['edts/elst'].lst[0]._replace(track_duration=nf_new)

		# 'mdhd' duration
		v_trak['mdia/mdhd'].update(duration=nf_new)
		t_trak['mdia/mdhd'].update(duration=nf_new)

		# 'stts' sample count/duration (depends on track)
		v_trak['mdia/minf/stbl/stts'].lst = [ AtomSTTS.lst_tuple()(sample_count=nf_new, sample_duration=1) ]
		t_trak['mdia/minf/stbl/stts'].lst = [ AtomSTTS.lst_tuple()(sample_count=1,      sample_duration=nf_new) ]

		# Build new list of frames offset/size
		v_stsz = v_trak['mdia/minf/stbl/stsz']
		v_stsz.update(num_entries=nf_new, sample_size=0)
		v_stsz.lst = []

		v_co64 = v_trak['mdia/minf/stbl/co64']
		v_co64.update(num_entries=nf_new)
		v_co64.lst = []

		for fo, fd in zip(self.frames_offset, self.frames_data):
			v_stsz.lst.append( v_stsz.lst_tuple()(size=len(fd)) )
			v_co64.lst.append( v_co64.lst_tuple()(offset=fo) )

		# Done
		return md_atom.serialize()

	def clear(self):
		# No frames
		self.frames_data = []
		self.frames_offset = []

		# Empty write list
		self.write_list = []
		self.write_offset = 0

		# Clean header
		self.header = bytearray(16)

	def add_chunk(self, data, offset=None):
		# Handle requested offset
		if offset is not None:
			if offset > self.write_offset:
				raise RuntimeError('Attempt to add chunk to already assigned parts')
			self.write_offset = offset

		# Add to the list
		self.write_list.append( (self.write_offset, data) )
		rv = self.write_offset

		# Next offset aligned to page
		self.write_offset += (len(data) + 4095) & ~4095

		# Return where it was placed
		return rv

	def write_chunks(self, fn):
		if os.path.exists(fn):
			raise RuntimeError('Not overwriting destination file')

		fh = open(fn, 'wb')

		for wo, wd in self.write_list:
			fh.seek(wo)
			fh.write(wd)

		fh.close()

	def handle_header(self):
		K_WIDE = 0x77696465		# 'wide'
		K_MDAT = 0x6d646174		# 'mdat'

		# Always use the 64b variant
		struct.pack_into('>IIQ', self.header, 0, 1, K_MDAT, self.write_offset)

	def handle_timecode(self):
		# Check timecode track is as we expect, a single 4 byte chunk @ 0x1000
		trak = self.src.md_atom['trak:%d' % self.src.trk_tim_idx]

		if ((trak['mdia/minf/stbl/stsz'].hdr.sample_size != 4) or
			(len(trak['mdia/minf/stbl/co64'].lst) != 1) or
			(trak['mdia/minf/stbl/co64'].lst[0].offset != 0x1000)):
			raise RuntimeError('Unexpected timecode track format')

		# Add it
		self.add_chunk(self.src.mv[0x1000:0x1004], 0x1000)

	def handle_frames(self):
		for f in self.frames_data:
			self.frames_offset.append( self.add_chunk(f) )

	def generate(self, dst_filename, n, start=0):
		# Reset
		self.clear()

		# Pick frames to write
		self.frames_data = self.src.frames[start::n]

		# Add header to write list (yet to be build)
		self.add_chunk(self.header)

		# Add timecode chunks
		self.handle_timecode()

		# Add video frames
		self.handle_frames()

		# Set metadata pointer in header
		self.handle_header()

		# Add metadata block
		self.add_chunk(self.build_metadata())

		# Write result
		self.write_chunks(dst_filename)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv0, src, dst, n, start=0):
	# Arguments
	n = int(n)
	start = int(start)

	br = BrawReader(src)
	br.parse()

	tl = BrawTimelapser(br)
	tl.generate(dst, n, start)

if __name__ == '__main__':
	main(*sys.argv)
