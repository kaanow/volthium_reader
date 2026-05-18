# Build the standalone C tests for volthium_lib.
#
# These tests don't depend on ESP-IDF — they build with any C11 compiler
# (clang on macOS, gcc on Linux). Run on a dev machine to validate the
# C port against its own test vectors, and against the Python ones in
# tests/test_wire_protocol.py.

CC      ?= cc
CFLAGS  ?= -std=c11 -Wall -Wextra -Werror -O2

TESTS = test_wire_protocol test_estimator

.PHONY: all test clean

all: $(TESTS)

test_wire_protocol: test_wire_protocol.c wire_protocol.c wire_protocol.h
	$(CC) $(CFLAGS) -o $@ test_wire_protocol.c wire_protocol.c

test_estimator: test_estimator.c estimator.c estimator.h
	$(CC) $(CFLAGS) -o $@ test_estimator.c estimator.c -lm

test: $(TESTS)
	@for t in $(TESTS); do ./$$t || exit 1; done

clean:
	rm -f $(TESTS)
