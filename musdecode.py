#!/usr/bin/env python3
from sys import argv

def on_off(v):
	return 'on' if v else 'off'


op_params = [
	lambda v: f"AM {on_off(v & 0x80)} PM {on_off(v & 0x40)} Sustain {on_off(v & 0x20)} KSR {on_off(v & 0x10)} Mult {v & 0xF}",
	lambda v: f"Level Scale {v >> 6} TL {v & 0x3F}",
	lambda v: f"AR {v >> 4} DR {v & 0xF}",
	lambda v: f"SL {v >> 4} RR {v & 0xF}",
	lambda v: f'Waveform {v & 3}'
]

chan_params = [
	lambda v: f"F-Number LSB {v:02X}",
	lambda v: f"F-Number MSB {v&3:X} Block {(v >> 2) & 7} Key {on_off(v & 0x20)}",
	lambda v: f"Feedback {(v >> 1) & 0x7} Alg {v & 1}"
]
cur_key_on = 0
max_key_on = 0

MAX_PARAM_CHANGES = 3

instruments = {}
inst_list = []
def find_instrument(inst):
	if inst in instruments:
		return instruments[inst]
	num = len(instruments)
	instruments[inst] = num
	inst_list.append(inst)
	return num

def describe_instrument(inst):
	feedback_alg = inst[0]

	print('  ' + chan_params[2](feedback_alg))
	for i in range(0, 2):
		print(f'  Operator {i+1}')
		for j in range(0, len(op_params)):
			print('    ' + op_params[j](inst[1 + i * 5 + j]))

def feedback(inst_num):
	feed_alg = inst_list[inst_num][0]
	return (feed_alg >> 1) & 7

def algo(inst_num):	
	feed_alg = inst_list[inst_num][0]
	return feed_alg & 1
	
def inst_vol(inst_num):
	inst = inst_list[inst_num]
	op2_tl = inst[7] & 0x3F
	vol = 63 - op2_tl
	if algo(inst_num):
		op1_tl = inst[2] & 0x3F
		vol += 63 - op1_tl
	return vol

#OPL2 AR 0 = OPN2 AR 0
#OPL2 AR 1 ~ OPN2 AR 5
#OPL2 AR 2 ~ OPN2 AR 7
#OPL2 AR 3 ~ OPN2 AR 9
#OPL2 AR 4 ~ OPN2 AR 11
#OPL2 AR 5 ~ OPN2 AR 13
#OPL2 AR 6 ~ OPN2 AR 15
def opn_instrument(inst):
	alg_feed = inst[0]
	op1 = inst[1:6]
	op2 = inst[6:]
	unused_op = (1, 0x3F, 0xFF, 0xFF, 0)
	ops = (op1, unused_op, op2, unused_op)
	output = bytearray()
	for op in ops:
		mult = op[0] & 0xF
		output.append(mult)
	for op in ops:
		tl = op[1] & 0x3F
		if tl == 0x3F:
			tl = 0x7F
		output.append(tl)
	for op in ops:
		ar = op[2] >> 4
		if ar:
			ar = min(31, 2 * ar + 3)
		output.append(ar)
	for op in ops:
		dr = op[2] & 0xF
		if dr:
			dr = min(31, 2 * dr + 3)
		#AMON
		dr |= (op[0] & 0x80)
		output.append(dr)
	for op in ops:
		rr = op[3] & 0xF
		sr = 0 if op[0] & 0x20 else rr * 2
		output.append(sr)
	for op in ops:
		#sl and rr
		output.append(op[3])
	for op in ops:
		#SSG-EG
		output.append(0)
	feedback = (alg_feed >> 1) & 7
	alg = alg_feed & 1
	alg = 7 if alg else 6
	output.append((feedback << 3) | alg)
	#TODO: AMS/PMS depth
	output.append(0xC0)
	#padding
	output.append(0)
	output.append(0)
	return output

#C4 - B4
frequencies = (
	261.6256, 277.1826, 293.6648, 311.1270, 329.6276, 349.2282, 
	369.9944, 391.9954, 415.3047, 440.0000, 466.1638, 493.8833
)
note_names = (
	'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'
)

accum_ts = 0
def accum_volume_share(ts):
	global accum_ts
	if ts > accum_ts:
		vol_sum = sum([chan.cur_vol for chan in channels])
		if vol_sum > 0:
			delta = ts - accum_ts
			for chan in channels:
				chan.volume_share_sum += delta * chan.cur_vol / vol_sum
		accum_ts = ts
		
class ChannelState:
	def __init__(self, num):
		self.num = num
		self.op_params = [[0]* 5, [0] * 5]
		self.chan_param = 0
		self.fnum = 0
		self.block = 0
		self.changes_since_last_note = []
		self.keyed = False
		self.inst_num = -1
		self.first_inst = -1
		self.all_insts = set()
		self.display = False
		self.events = []
		self.opn_map = None
		self.volume_share_sum = 0
		self.cur_vol = 0
	def op_reg(self, op, reg, val, ts):
		if reg >= 0xE0:
			param = 4
		else:
			param = (reg >> 5) - 1
		if val != self.op_params[op - 1][param]:
			self.changes_since_last_note.append(('op', op, param, val, self.op_params[op - 1][param], ts))
			self.op_params[op - 1][param] = val
	def chan_reg(self, reg, val, ts):
		reg = reg >> 4
		if reg == 0xC:
			if val != self.chan_param:
				self.changes_since_last_note.append(('chan', val, self.chan_param, ts))
				self.chan_param = val
		elif reg == 0xA:
			self.fnum &= 0x300
			self.fnum |= val
		else:
			self.fnum &= 0x0FF
			self.fnum |= (val & 3) << 8
			self.block = (val >> 2) & 7
			if val & 0x20:
				self.key_on(ts)
			else:
				self.key_off(ts)
			
	def key_on(self, ts):
		if len(self.changes_since_last_note) < MAX_PARAM_CHANGES:
			for change in self.changes_since_last_note:
				if change[0] == 'op':
					_,op,param,val,old,cts = change
					self.events.append((cts, 'op', self.num, op, param, val))
					if self.display:
						desc = op_params[param](val)
						old_desc = op_params[param](old)
						print(f'Chan {self.num} Op {op}\n  New: {desc}\n  Old: {old_desc} @ {cts}')
				else:
					_,val,old,cts = change
					self.events.append((cts, 'chan', self.num, val))
					if self.display:
						desc = chan_params[2](val)
						old_desc = chan_params[2](desc)
						print(f'Chan {self.num}\n  New: {desc}\n  Old: {old_desc} @ {cts}')
		else:
			inst_num = find_instrument(self.to_instrument())
			if inst_num != self.inst_num:
				if self.display:
					print(f'Channel {self.num} Instrument {inst_num}')
				self.events.append((ts - 1, 'inst', self.num, inst_num))
				self.inst_num = inst_num
				self.all_insts.add(inst_num)
				if self.first_inst < 0:
					self.first_inst = inst_num
		self.changes_since_last_note = []
		if self.display:
			hz = self.fnum * 49716.0 / pow(2, 20-self.block)
			octave = 4
			mult = 1
			minf = frequencies[0]
			maxf = frequencies[-1]
			while hz * 1.05 < minf:
				octave -= 1
				mult *= 0.5
				minf /= 2
				maxf /= 2
			while hz > maxf * 1.05:
				octave += 1
				mult *= 2
				minf *= 2
				maxf *= 2
			note_num = None
			min_diff = None
			for i in range(0, len(frequencies)):
				freq = frequencies[i]
				diff = abs(freq * mult - hz)
				if min_diff is None or diff < min_diff:
					min_diff = diff
					note_num = i
			cents_base = mult * (frequencies[i+1] - frequencies[i] if i < len(frequencies) - 1 else frequencies[i] - frequencies[i - 1])
			print(f'Channel {self.num} Key On - Block {self.block}, FNum {self.fnum} ({self.fnum:X}) {hz}Hz {note_names[note_num]}{octave} (off by {100 * min_diff / cents_base} cents) @ {ts}')
			self.events.append((ts, 'keyon', self.num, octave, note_num))
		if not self.keyed:
			global cur_key_on, max_key_on
			accum_volume_share(ts)
			self.cur_vol = inst_vol(self.inst_num)
			cur_key_on += 1
			max_key_on = max(max_key_on, cur_key_on)
			self.keyed = True
	
	def key_off(self, ts):
		if self.keyed:
			accum_volume_share(ts)
			if self.display:
				print(f'Channel {self.num} Key Off @ {ts}')
			self.events.append((ts, 'keyoff', self.num))
			global cur_key_on
			cur_key_on -= 1
			self.cur_vol = 0
			self.keyed = False
	
	def to_instrument(self):
		return tuple([self.chan_param] + self.op_params[0] + self.op_params[1])
		
	def reset(self):
		global accum_ts
		self.inst_num = self.first_inst
		self.all_insts.add(self.first_inst)
		inst = inst_list[self.first_inst]
		self.chan_param = inst[0]
		self.op_params[0] = list(inst[1:6])
		self.op_params[1] = list(inst[6:])
		self.freq = self.block = 0
		self.keyed = False
		self.changes_since_last_note = []
		self.events = []
		self.opn_map = None
		self.volume_share_sum = 0
		self.cur_vol = 0
		accum_ts = 0

channels = [ChannelState(i) for i in range(1, 10)]

def op_reg_to_channel(reg):
	channel = (reg & 0x7) % 3
	if channel >= 3:
		channel -= 3
	if reg & 8:
		channel += 3
	if reg & 0x10:
		channel += 6
	channel += 1
	return channel

def process_events(f, num_events):
	global channels
	ts = 0
	for _ in range(0, num_events):
		event = f.read(4)
		reg = event[0]
		if not reg:
			continue
		val = event[1]
		delay = event[2] | (event[3] << 8)
		ts += delay
		if (reg >= 0x20 and reg < 0xA0) or reg >= 0xE0:
			channel = op_reg_to_channel(reg)
			op = reg & 7
			op = 1 if op < 3 else 2
			param = (reg >> 5) - 1
			if param == 6:
				param = 4
			#desc = op_params[param](val)
			#desc = f'Chan {channel} Op {op} {desc} Delay {delay}'
			channels[channel - 1].op_reg(op, reg, val, ts)
		elif reg >= 0xA0 and reg < 0xD0 and reg != 0xBD:
			channel = (reg & 0xF) + 1
			#desc = chan_params[(reg >> 4) - 0xA](val)
			#desc = f'Chan {channel} {desc} Delay {delay}'
			channels[channel - 1].chan_reg(reg, val, ts)
		else:
			print(f'Reg {reg:02X} Val {val:02X} @ {ts}')
			
with open(argv[1], 'rb') as f:
	lenbytes  = f.read(2)
	length = lenbytes[0] | (lenbytes[1] << 8)
	num_events = length // 4
	process_events(f, num_events)
	for i in range(0, len(inst_list)):
		print(f'Instrument {i}: {inst_list[i]}')
		describe_instrument(inst_list[i])
	for i in range(0, len(channels)):
		chan = channels[i]
		other_insts = set(chan.all_insts)
		if other_insts:
			other_insts.remove(chan.first_inst)
			other_insts = list(other_insts)
			other_insts.sort()
		others = "None" if len(other_insts) == 0 else ", ".join([str(x) for x in other_insts])
		print(f'Channel {i+1} Initial Instrument: {chan.first_inst} Others: {others} Volume Share Sum: {chan.volume_share_sum}')
	for chan in channels:
		chan.reset()
		chan.display = True
	f.seek(2)
	process_events(f, num_events)
opl2_used = len([chan for chan in channels if chan.first_inst >= 0])
print(f'Max key on {max_key_on}, OPL2 channels used {opl2_used}')
if opl2_used > max_key_on:
	print('WARNING: Song could potentially benefit from dynamic channel mapping!')
avail_channels = [6,5,4,2,1,0]
opn_instruments = [opn_instrument(inst) for inst in inst_list]
ch3_split = False
inst_map = list(range(0, len(inst_list)))

def highest_sum_chan(chans):
	ret = None
	highest_share = 0
	for cand in chans:
		if cand.volume_share_sum > highest_share:
			highest_share = cand.volume_share_sum
			ret = cand
	return ret
	
def lowest_sum_chan(chans):
	ret = None
	lowest_share = None
	for cand in chans:
		if lowest_share is None or cand.volume_share_sum < lowest_share:
			lowest_share = cand.volume_share_sum
			ret = cand
	return ret

def lowest_feedback(chans):
	ret = []
	lowest_feedback = 255
	for cand in chans:
		fb = feedback(cand.first_inst)
		print(cand.num, cand.first_inst, fb, lowest_feedback)
		if fb < lowest_feedback:
			ret = [cand]
			lowest_feedback = fb
		elif fb == lowest_feedback:
			ret.append(cand)
	return ret

MAX_SPLIT_FEEDBACK = 1
def ch3_split2(share_candidates):
	global inst_map
	secondary_candidates = lowest_feedback(share_candidates)
	print(secondary_candidates[0].num, secondary_candidates[0].first_inst, feedback(secondary_candidates[0].first_inst))
	desired_feedback = 0
	secondary = None
	if feedback(secondary_candidates[0].first_inst) <= MAX_SPLIT_FEEDBACK:
		if feedback(secondary_candidates[0].first_inst):
			#We found a close fit for channel sharing, choose the least important one
			secondary = lowest_sum_chan(secondary_candidates)
		else:
			#We found a perfect fit for channel sharing, choose the most important one
			#this will keep it away from channel 6 which gets interrupted for PCM sounds
			secondary = highest_sum_chan(secondary_candidates)
	else:
		#All the candidates use feedback and will sound different
		#choose the one with the lowest share so it will be less noticeable
		if opl2_used == max_key_on:
			secondary = lowest_sum_chan(share_candidates)
		else:
			#We can avoid dropped notes by dynamically assigning channels
			return False
	share_candidates.remove(secondary)
	primary = highest_sum_chan(share_candidates)
	if algo(primary.first_inst):
		if algo(secondary.first_inst):
			alg = 7
		else:
			#ruh roh
			for cand in share_candidates:
				if not algo(cand.first_inst):
					primary = cand
					break
			if algo(primary.first_inst):
				print('Error: bad algorithm combo Channel {primary.num} & {second.num} Instrument {primary.first_inst} & {secondary.first_inst}')
				exit(1)
			alg = 4
	elif algo(secondary.first_inst):
		alg = 6
	else:
		alg = 4
	primary.opn_map = 0x9
	secondary.opn_map = 0xE
	print(f'Channel {primary.num} mapped to OPN2 channel 3 operators 1 & 2')
	print(f'Channel {secondary.num} mapped to OPN2 channel 3 operators 3 & 4')
	instrument = bytearray(opn_instruments[primary.first_inst])
	#replace algorithm with newly calculated one
	instrument[28] &= 0x38
	instrument[28] |= alg
	second_inst = opn_instruments[secondary.first_inst]
	for base in range(0, 28, 4):
		instrument[base + 1] = second_inst[base]
		instrument[base + 3] = second_inst[base + 2]
	secondary_usage = 0
	primary_usage = 0
	for chan in channels:
		if primary.first_inst in chan.all_insts:
			primary_usage += 1
		if secondary.first_inst in chan.all_insts:
			secondary_usage += 1
	if secondary_usage <= 1:
		inst_map = [num if num < secondary.first_inst else num -1 for num in inst_map]
		del opn_instruments[secondary.first_inst]
	if primary_usage > 1:
		primary.first_inst = primary.inst_num = len(opn_instruments)
		opn_instruments.append(instrument)
		inst_map.append(primary.first_inst)
	else:
		opn_instruments[inst_map[primary.first_inst]] = instrument
	return True
	
def ch3_split3(share_candidates):
	global inst_map
	#This channel will be protected from interruption by PCM so we picked the highest share one
	primary = highest_sum_chan(share_candidates)
	share_candidates.remove(primary)
	#These channels will be heavily impacted since they are being reduced to single operator
	#choose the lowest share ones
	secondary = lowest_sum_chan(share_candidates)
	share_candidates.remove(secondary)
	tertiary = lowest_sum_chan(share_candidates)
	primary.opn_map = 0x9
	secondary.opn_map = 0xA
	tertiary.opn_map = 0xC
	print(f'Channel {primary.num} mapped to OPN2 channel 3 operators 1 & 2')
	print(f'Channel {secondary.num} mapped to OPN2 channel 3 operator 3')
	print(f'Channel {tertiary.num} mapped to OPN2 channel 3 operator 4')
	instrument = bytearray(opn_instruments[primary.first_inst])
	second_inst = opn_instruments[secondary.first_inst]
	third_inst = opn_instruments[tertiary.first_inst]
	for base in range(0, 28, 4):
		instrument[base + 1] = second_inst[base + 2]
		instrument[base + 3] = third_inst[base + 2]
	primary_usage = 0
	secondary_usage = 0
	tertiary_usage = 0
	for chan in channels:
		if primary.first_inst in chan.all_insts:
			primary_usage += 1
		if secondary.first_inst in chan.all_insts:
			secondary_usage += 1
		if tertiary.first_inst in chan.all_insts:
			tertiary_usage += 1
	if primary_usage > 1:
		primary.first_inst = primary.inst_num = len(opn_instruments)
		inst_map.append(primary.first_inst)
		opn_instruments.append(instrument)
	else:
		opn_instruments[primary.first_inst] = instrument
	to_del = []
	if secondary_usage <= 1:
		to_del.append(secondary.first_inst)
	if tertiary_usage <= 1:
		to_del.append(tertiary.first_inst)
	to_del.sort()
	while to_del:
		del_num = to_del.pop()
		inst_map = [num if num < del_num else num -1 for num in inst_map]
		del opn_instruments[del_num]
	return True
	

dynamic_map = False
static_channels = set()
if opl2_used > 6:
	share_candidates = [chan for chan in channels if len(chan.all_insts) == 1 and chan.first_inst >= 0]
	if len(share_candidates) < (opl2_used - 5):
		print(f'{opl2_used} channels in source, but only {len(share_candidates)} share candidates found, needed {opl2_used - 5}')
		dynamic_map = True
	else:
		if opl2_used > 7:
			success = ch3_split3(share_candidates)
		else:
			success = ch3_split2(share_candidates)
		if success:
			ch3_split = True
			avail_channels.remove(2)
		else:
			dynamic_map = True
			
def handle_op_event(out, chan, event):
	tl = event[5] & 0x3F
	if tl == 0x3F:
		tl = 0x7F
	op = event[3]
	if chan == 0x9:
		chan = 2
		reg = 0x42
	elif chan == 0xE:
		chan = 2
		reg = 0x46
	elif chan == 0xA:
		chan = 2
		if op == 2:
			reg = 0x46
			op = 0
		else:
			print(f'skipping event due to ch3 split operator drop', event)
			return False
	elif chan == 0xC:
		chan = 2
		if op == 2:
			reg = 0x4E
			op = 0
		else:
			print(f'skipping event due to ch3 split operator drop', event)
			return False
	else:
		reg = 0x40 + (chan & 3)
	ret = 1
	if (chan & 4) != (last_chan & 4):
		#set "part"
		out.write(bytes((0xE0 | ((chan >> 1) & 2),)))
		print(f'Manual part set {(chan >> 1) & 2}')
		ret ++ 1
	
	if op == 2:
		reg += 8
	print(f'New TL for Channel {chan}, Op {op}, Reg {reg:02X}, value {tl:02X}')
	out.write(bytes((reg, tl)))
	return ret

if len(argv) > 2:
	with open(argv[2], 'wb') as out:
		#if argv[1].endswith('DUNGEON.MUS'):
		#	channels[3].opn_map = 0
		#	avail_channels.remove(0)
		events = []
		opl_instruments = None
		opn_cur_inst = None
		opn_keyed_on_ts = None
		opl_deffered_op_updates = None
		if dynamic_map:
			print(f'Using dynamic channel mapping')
			opn_cur_inst = [-1] * 7
			opl_instruments = []
			opn_keyed_on_ts = [-1] * 7
			opl_deffered_op_updates = []
			for chan in channels:
				if chan.num in static_channels:
					events.append((0, 'inst', chan.num, chan.first_inst))
				opl_instruments.append(inst_map[chan.first_inst])
				opl_deffered_op_updates.append({})
				chan.keyed = False
				if chan.first_inst >= 0:
					events += chan.events
		else:
			print(f'Using static channel mapping')
			needs_assign = [chan for chan in channels if chan.first_inst >= 0 and chan.opn_map is None]
			while len(needs_assign) > len(avail_channels):
				to_remove = lowest_sum_chan(needs_assign)
				print(f'Omitting channel {to_remove.num}')
				needs_assign.remove(to_remove)
			print(avail_channels)
			print([chan.num for chan in needs_assign])
			if len(avail_channels) == len(needs_assign):
				#channel 6 will get interrupt, try to stick the least important thing there
				chan6 = lowest_sum_chan(needs_assign)
				print(f'Channel {chan6.num} mapped to OPN2 channel 6')
				chan6.opn_map = 6
				needs_assign.remove(chan6)
			#we either assigned something to OPN2 channel 6 or we don't need it
			avail_channels.remove(6)
			for chan in needs_assign:
				chan.opn_map = avail_channels.pop()
				print(f'Channel {chan.num} mapped to OPN2 channel {chan.opn_map}')
			
			for chan in channels:
				if not chan.opn_map is None:
					if chan.opn_map <= 0x9:
						events.append((0, 'inst', chan.num, chan.first_inst))
					events += chan.events
		events.sort()
		out.write(bytes((len(opn_instruments), )))
		for inst in opn_instruments:
			out.write(inst)
		out.write(bytes((0x27,0x5F if ch3_split else 0x1F)))
		out_ts = 0
		out_hz = 7609.576955782
		in_hz = 700 #seems suspiciously round
		last_chan = None
		for event in events:
			evt_ts = event[0]
			etype = event[1]
			chan = event[2]
			if not dynamic_map:
				if channels[chan-1].opn_map is None:
					print('Skipping event', event, f'because channel {chan} is not mapped')
					continue
				else:
					chan = channels[chan-1].opn_map
				if etype == 'inst' and chan == 0x9:
					chan = 2
			ts_in_out = round(evt_ts * out_hz / in_hz)
			if ts_in_out >= out_ts + 6:
				diff = ts_in_out - out_ts
				while diff:
					if diff <= 176:
						diff = max(0, round((diff - 11) / 11))
						diff &= 0xF
						out_ts += diff * 11 + 11
						out.write(bytes((diff,)))
						diff = 0
					else:
						diff -= 176
						out_ts += 176
						if diff > 0xFFF:
							diff -= 0xFFF
							out_ts += 0xFFF
							out.write(bytes((0x1F, 0xFF)))
						else:
							out.write(bytes((0x10 | (diff >> 8), diff & 0xFF)))
							out_ts += diff
							diff = 0
			out_ts += 1
			if etype == 'inst':
				inst_num = inst_map[event[3]]
				if dynamic_map:
					if chan in static_channels:
						chan = channels[chan-1].opn_map
					else:
						opl_instruments[chan - 1] = inst_num
						continue
				out.write(bytes((0xF0 | chan, inst_num)))
				last_chan = chan
			elif etype == 'keyon':
				octave = event[3]
				note_num = event[4]
				if dynamic_map:
					channels[chan-1].keyed = True
					if chan in static_channels:
						c = channels[chan-1].opn_map
					elif channels[chan-1].opn_map in avail_channels and opl_instruments[chan-1] == opn_cur_inst[channels[chan-1].opn_map]:
						#OPN channel most recently used for this OPL channel is still available
						#and hasn't been used for a different instrument since, so reuse it
						c = channels[chan-1].opn_map
						avail_channels.remove(c)
					elif avail_channels:
						#there are free channels available, pick one of those
						found_same_inst = False
						for c in avail_channels:
							if opn_cur_inst[c] == opl_instruments[chan-1]:
								channels[chan-1].opn_map = c
								print(f'Assigned Channel {chan} to OPN2 channel {c}')
								found_same_inst = True
								break
						if not found_same_inst:
							c = avail_channels[0]
							opn_cur_inst[c] = opl_instruments[chan-1]
							out.write(bytes((0xF0 | c, opn_cur_inst[c])))
							out_ts += 1
							channels[chan-1].opn_map = c
							print(f'Assigned Channel {chan} to OPN2 channel {c} and switching to instrument {opl_instruments[chan-1]}')
						avail_channels.remove(c)
					else:
						#pick the least most recently keyed-on channel
						min_key_on_ts = None
						c = None
						for i in range(0, len(opn_keyed_on_ts)):
							if i == 3:
								#not a real channel
								continue
							if min_key_on_ts is None or opn_keyed_on_ts[i] < min_key_on_ts:
								min_key_on_ts = opn_keyed_on_ts[i]
								c = i
						print(f'Assigned Channel {chan} to in-use OPN2 channel {c}')
						if opn_cur_inst[c] != opl_instruments[chan - 1]:
							old_inst = opn_instruments[opn_cur_inst[c]]
							for i in range(0, 4):
								rr = old_inst[20 + i] & 4
								if rr != 0xF:
									#set max release rate, to avoid unwanted output
									#during/after instrument change
									if (last_chan & 4) != (c & 4):
										last_chan = c
										out.write(bytes((0xE0 | ((c >> 1) & 2),)))
										print(f'Manual part set {(chan >> 1) & 2}')
									print(f'Forced max RR - Reg {0x80 | (c & 3) | (i * 4)}, Val {old_inst[20 + i] | 0xF}')
									out.write(bytes((0x80 | (c & 3) | (i * 4), old_inst[20 + i] | 0xF)))
									out_ts += 1
						print(f'Forced key-off {c}')
						out.write(bytes((0xD0 | c,)))
						out_ts += 1
						if opn_cur_inst[c] != opl_instruments[chan - 1]:
							opn_cur_inst[c] = opl_instruments[chan-1]
							print(f'Swicthed channel {c} to instrument {opl_instruments[chan-1]}')
							out.write(bytes((0xF0 | c, opn_cur_inst[c])))
							out_ts += 1
						for channel in channels:
							if channel.opn_map == c:
								channel.opn_map == None
								channel.keyed = False
						channels[chan-1].opn_map = c
					if opl_deffered_op_updates[chan-1]:
						deferred = opl_deffered_op_updates[chan-1]
						opl_deffered_op_updates[chan-1] = {}
						for key in deferred:
							event = deferred[key]
							out_ts += handle_op_event(out, c, event)
					print(f'Key on OPL2 channel {chan} OPN2 channel {c}, avail_channels {avail_channels}')
					chan = c
					opn_keyed_on_ts[chan] = out_ts 
				out.write(bytes((0xC0 | chan, (note_num + octave * 12) * 2)))
				if chan > 0x8:
					chan = 2
				last_chan = chan
			elif etype == 'keyoff':
				if dynamic_map:
					channels[chan-1].keyed = False
					c = channels[chan-1].opn_map
					if c is None:
						#channel was already keyed off so it could be re-used
						continue
					if not chan in static_channels:
						avail_channels.append(c)
					print(f'Key off OPL2 channel {chan}, OPN2 channel {c}, avail_channels {avail_channels}')
					chan = c
				out.write(bytes((0xD0 | chan,)))
				if chan > 0x8:
					chan = 2
				last_chan = chan
			elif etype == 'op' and event[4] == 1:
				if dynamic_map:
					if channels[chan-1].keyed or c in static_channels:
						chan = channels[chan-1].opn_map
					else:
						opl_deffered_op_updates[chan-1][(event[3], event[4])] = event
						continue
				ts_diff = handle_op_event(out, chan, event)
				if ts_diff > 1:
					out_ts += ts_diff - 1
				elif ts_diff == 0:
					out_ts -= 1
				last_chan = chan
			else:
				print('skipping event', event)

