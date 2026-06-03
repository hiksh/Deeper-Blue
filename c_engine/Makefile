# Makefile for Deeper-Blue C Engine

CC      = gcc
CFLAGS  = -O3 -march=native -std=c11 -Wall -Wextra
TARGET_WIN = deeper_blue.exe
TARGET_LIN = deeper_blue

# Auto-detect OS
ifeq ($(OS),Windows_NT)
    TARGET = $(TARGET_WIN)
    RM     = del /Q
else
    TARGET = $(TARGET_LIN)
    RM     = rm -f
endif

# Auto-enable Fathom Syzygy tablebases if tbprobe.c is present
ifneq ($(wildcard tbprobe.c),)
    FATHOM_FLAGS = -DFATHOM
    FATHOM_SRCS  = tbprobe.c
    $(info Fathom detected — building with Syzygy support)
else
    FATHOM_FLAGS =
    FATHOM_SRCS  =
endif

all: $(TARGET)

$(TARGET): engine.c $(FATHOM_SRCS)
	$(CC) $(CFLAGS) $(FATHOM_FLAGS) -I. -o $@ engine.c $(FATHOM_SRCS) -lm

clean:
	$(RM) $(TARGET_WIN) $(TARGET_LIN)

# Quick test: print engine info via UCI
test: $(TARGET)
	echo "uci\nquit" | ./$(TARGET)

.PHONY: all clean test
