#!/usr/bin/env python3
from sys import argv

if len(argv) < 4:
	print('Usage: combine.py DRIVER SONG OUTPUT')

driver = None
with open(argv[1], 'rb') as df:
	driver = df.read()
song = None
with open(argv[2], 'rb') as sf:
	song = sf.read()
	
output = bytearray(driver)
#remove stub song
del output[-1]
inst_start = len(output)
num_insts = song[0]
output += song[1:]
stream_start = inst_start + num_insts * 32
stream_end = len(output)
output[6] = inst_start & 0xFF
output[7] = inst_start >> 8
output[8] = stream_start & 0xFF
output[9] = stream_start >> 8
output[10] = stream_end & 0xFF
output[11] = stream_end >> 8
with open(argv[3], 'wb') as out:
	out.write(output)
