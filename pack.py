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
start_teramusic = int(defines.get('STARTTERAMUSIC', 0))
if start_teramusic:
	num_songs = start_teramusic - start_music
else:
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
if start_teramusic >= len(offsets):
	print(f'Expected at least {start_teramusic+1} offsets in AUDIOHED.WL6')
	exit(1)

tera_files = []
for index in range(0, len(songs)):
	song = songs[index]
	filename = 'music/' + song.lower().replace('_mus', '.opn')
	with open(filename, 'rb') as f:
		tera_files.append(f.read())
	end_off = start_teramusic + index + 1
	end = len(tera_files[index]) + 2 + offsets[end_off-1]
	if end_off == len(offsets):
		offsets.append(end)
	else:
		offsets[end_off] = end

with open('WOLF3D/AUDIOHED.WL6', 'wb') as audiohed:
	for offset in offsets:
		b = bytes((offset & 0xFF, (offset >> 8) & 0xFF, (offset >> 16) & 0xFF, offset >> 24))
		audiohed.write(b)

with open('WOLF3D/AUDIOT.WL6', 'r+b') as audiot:
	audiot.truncate(offsets[start_teramusic])
	audiot.seek(offsets[start_teramusic])
	for song in tera_files:
		size = len(song)
		audiot.write(bytes((size & 0xFF, size >> 8)))
		audiot.write(song)

		