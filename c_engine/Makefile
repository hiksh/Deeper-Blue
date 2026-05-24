# Makefile for Deeper-Blue C Engine

CC      = gcc
CFLAGS  = -O3 -march=native -std=c11 -Wall -Wextra -lm
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

all: $(TARGET)

$(TARGET): engine.c
	$(CC) $(CFLAGS) -o $@ engine.c -lm

clean:
	$(RM) $(TARGET_WIN) $(TARGET_LIN)

# Quick test: print engine info via UCI
test: $(TARGET)
	echo "uci\nquit" | ./$(TARGET)

.PHONY: all clean test
