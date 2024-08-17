.SUFFIXES:
.PHONY: all

all: player.z80

%.z80 : %.sz8
	vasmz80_oldstyle -Fbin -o $@ $< -L $@.list
