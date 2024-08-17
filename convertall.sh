#!/bin/sh

for file in music/*.MUS; do 
	out=`echo "$file" | sed -Ee 's/^([^.]+)\..*$/\L\1.opn/'`;
	txt=`echo "$out" | sed -e 's/\.opn/\.txt/'`;
	combine_out=`echo "$out" | sed -e 's/\.opn/\.z80/'`;
	echo "$out";
	./musdecode.py "$file" "$out" > "$txt" && 
	./combine.py z80_player/player.z80 "$out" "$combine_out"
done
