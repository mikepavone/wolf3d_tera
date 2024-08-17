#!/usr/bin/env python3
defines = {}
enums = {}
enum_counter = None
current_enum = None
with open('WOLFSRC/AUDIOWL6.H') as header:
	for line in header:
		if enum_counter is None:
			start,_,rest = line.partition(' ')
			if start == '#define':
				name,_,val = rest.expandtabs(1).partition(' ')
				defines[name] = val.strip()
			elif start == 'typedef':
				if rest.startswith('enum'):
					enum_counter = 0
					current_enum = []
		else:
			line = line.strip()
			if line.startswith('}'):
				name = line[1:].strip()[0:-1]
				enums[name] = current_enum
				enum_counter = current_enum = None
			else:
				name,comma,_ = line.partition(',')
				if comma:
					current_enum.append(name)
					

num_sounds = int(defines.get('NUMSOUNDS', 0))
sounds = enums.get('soundnames', [])
if num_sounds != len(sounds):
	print(f'NUMSOUNDS is {num_sounds}, but soundnames has {len(sounds)} entries')
	exit(1)
start_music = int(defines.get('STARTMUSIC', 0))
num_chunks = int(defines.get('NUMSNDCHUNKS', 0))
num_songs = num_chunks - start_music
songs = enums.get('musicnames', [])
if num_songs != len(songs):
	print(f'Expected {num_songs} songs because STARTMUSIC is {start_music} and NUMSNDCHUNKS is {num_chunks}, but musicnames has {len(songs)} entries')
	exit(1)

offsets = []
with open('WOLF3D/AUDIOHED.WL6', 'rb') as audiohed:
	while True:
		offset = audiohed.read(4)
		if len(offset) < 4:
			break
		offsets.append(offset[0] | (offset[1] << 8) | (offset[2] << 16) | (offset[3] << 24))
start_pc = int(defines.get('STARTPCSOUNDS', 0))
start_adlib = int(defines.get('STARTADLIBSOUNDS', 0))
start_digi = int(defines.get('STARTDIGISOUNDS', 0))

def write_chunk(audiot, offset, size, name):
	audiot.seek(offset)
	data = audiot.read(size)
	with open(name, 'wb') as out:
		out.write(data)

with open('WOLF3D/AUDIOT.WL6', 'rb') as audiot:
	for i in range(0, num_sounds):
		name = sounds[i]
		print(f'exporting sound {name}')
		for start,ext in ((start_pc, "pc"), (start_adlib, "adlib"), (start_digi, "digi")):
			offset = offsets[start + i]
			size = offsets[start + i + 1] - offset
			if size:
				write_chunk(audiot, offset, size, f"sounds/{name}.{ext}")
	for i in range(0, num_songs):
		name = songs[i].replace('_MUS', '.MUS')
		print(f'exporting song {name}')
		offset = offsets[start_music + i]
		size = offsets[start_music + i + 1] - offset
		write_chunk(audiot, offset, size, f"music/{name}")
		