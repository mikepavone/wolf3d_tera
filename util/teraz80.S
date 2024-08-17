	org 0x100
	CPU 286
	BITS 16

TD_BASE equ 0x1100
TD_FW_PAGE equ 0x60
TD_TMSS_FW_PAGE equ 0x21
TD_WINDOW equ 0x62
TD_WINDOW_CTRL equ 0x63
TD_FW_TO_MD equ 1
TD_PC_TO_MD_WINDOW equ 2
TD_SWITCH equ 0x64
TD_SWITCH_TO_68K equ 1
TD_SWITCH_MAP equ 2
TD_SWITCH_VID equ 4
TD_SWITCH_BASE equ 0x80
TD_STATUS equ 0x65
TD_M68K_PAGE equ 0x66

COMMAND_LINE equ 0x81

OUTPUT_CHAR equ 0x02
OUTPUT_STRING equ 0x09
OPEN_FILE equ 0x3D
CLOSE_FILE equ 0x3E
READ_FILE equ 0x3F
DOS_EXIT equ 0x4C
	
	;check if we're already unlocked
	mov dx, TD_BASE|TD_STATUS
	in al, dx
	test al, 0x20
	jnz already_unlocked
	;unlock MD side
	mov ax, cs
	shr ax, 8
	call md_unlock
	
	mov dl, TD_STATUS
	in al, dx
	test al, 0x20
	jz exit_unlock_fail
	
already_unlocked:
	;open file passed on command line
	mov si, COMMAND_LINE
.loop:
	mov al, [si]
	inc si
	cmp al, 0x0D
	je exit_no_filename
	cmp al, ' '
	jne .loop
	
	mov dx, si
	dec si
.loop2:
	inc si
	mov al, [si]
	cmp al, ' '
	je .done
	cmp al, 0x0D
	jne .loop2
.done:
	mov byte [si], 0
	
	mov ax, OPEN_FILE<<8
	int 21h
	jc exit_open_fail
	mov bx, ax
	
	
	;get base address of window
	mov dx, TD_BASE|TD_WINDOW
	in al, dx
	shl ax, 8
	mov ds, ax
	
	;enable access to MD memory space in window
	inc dl ;TD_WINDOW_CTRL
	mov al, TD_FW_TO_MD|TD_PC_TO_MD_WINDOW
	out dx, al
	
	;select IO and bus arbiter page
	mov dl, TD_M68K_PAGE
	mov ax, 0xA10
	out dx, ax
	
	;bus request z80
	mov byte [0x1100], 1
	;release Z80 reset
	mov byte [0x1200], 1
	
	;select Z80 ram page
	mov ax, 0xA00
	out dx, ax
	
	xor dx, dx
	mov ah, READ_FILE
	mov cx, 0x2000 ;MD window s8ze
	int 21h
	jc exit_read_fail
	cmp ax, 0x2000
	jnz read_done
	
	;select 2nd 8K page of Z80 RAM
	mov ax, 0xA02
	mov dx, TD_BASE|TD_M68K_PAGE
	out dx, ax
	
	xor dx, dx
	mov ah, READ_FILE
	mov cx, 0x2000
	int 21h
	jc exit_read_fail
read_done:
	mov ah, CLOSE_FILE
	int 21h
	
	;select IO and bus arbiter page
	mov dx, TD_BASE|TD_M68K_PAGE
	mov ax, 0xA10
	out dx, ax
	
	;reset Z80
	mov byte [0x1200], 0
	;release bus request
	mov byte [0x1100], 0
	nop
	nop
	nop
	nop
	;release Z80 reset
	mov byte [0x1200], 1
	
exit:
	mov ax, DOS_EXIT<<8
	int 21h
exit_unlock_fail:
	mov dx, err_fail_unlock
	mov ah, OUTPUT_STRING
	int 21h
	mov ax, (DOS_EXIT<<8)|1
	int 21h
exit_no_filename:
	mov dx, err_no_filename
	mov ah, OUTPUT_STRING
	int 21h
	mov ax, (DOS_EXIT<<8)|1
	int 21h
exit_open_fail:
	mov si, dx
	mov dx, err_fail_open
	mov ah, OUTPUT_STRING
	int 21h
	call print_asciiz
	mov ax, (DOS_EXIT<<8)|2
	int 21h
exit_read_fail:
	mov ax, cs
	mov ds, ax
	mov ah, CLOSE_FILE
	int 21h
	mov dx, err_fail_read
	mov ah, OUTPUT_STRING
	int 21h
	mov ax, (DOS_EXIT<<8)|3
	int 21h
	
md_unlock:
	mov dx, TD_BASE|TD_M68K_PAGE ;0x1166
	
	out dx, ax
	
	mov dl, TD_FW_PAGE
	mov al, TD_TMSS_FW_PAGE
	out dx, al
	
	mov dl, TD_WINDOW_CTRL
	mov al, TD_FW_TO_MD
	out dx, al
	
	inc dl
	mov al, TD_SWITCH_BASE|TD_SWITCH_TO_68K
	out dx, al
	
	mov ax, 0xFFFF
.waitlp:
	dec ax
	jnz .waitlp
	retn
	
print_asciiz:
	mov ah, OUTPUT_CHAR
.loop:
	mov dl, [si]
	cmp dl, 0
	jz .done
	inc si
	int 21h
	jmp .loop
.done:
	retn

newline:
	mov ah, OUTPUT_CHAR
	mov dl, 13
	int 21h
	mov dl, 10
	int 21h
	retn
	
	
	align 2
tmss_string:
	db "PRODUCED BY OR UNDER LICENSE FROM SEGA ENTERPRISES Ltd.", 0
err_fail_unlock:
	db "Failed to unlock MD hardware$"
err_no_filename:
	db "USAGE: teraz80 FILE$"
err_fail_open:
	db "Failed to open file: $"
err_fail_read:
	db "Failed to read file$"

