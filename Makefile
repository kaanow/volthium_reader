# Top-level Makefile — convenience targets that run every test in
# the repo with one command. Lower-level targets in each sub-tree
# (scripts/, firmware/common/volthium_lib/) still work independently.
#
# Usage:
#     make            # default = test
#     make test       # all Python + C tests + cross-validation
#     make test-py    # Python only
#     make test-c     # C only
#     make vectors    # regenerate Python test-vector .bin files
#     make clean      # remove compiled C binaries
#     make help       # this list

PYTHON ?= .venv/bin/python
VOLTHIUM_LIB := firmware/common/volthium_lib

.PHONY: default test test-py test-c vectors clean help

default: test

help:
	@echo "available targets:"
	@echo "  make test       — run all tests (Python + C + cross-validation)"
	@echo "  make test-py    — Python tests only (volthium/* via unittest)"
	@echo "  make test-c     — C tests only (firmware/common/volthium_lib/)"
	@echo "  make vectors    — regenerate the Python test-vector .bin files"
	@echo "  make clean      — remove compiled C test binaries"

test: test-py test-c
	@echo ""
	@echo "=========================================="
	@echo "  all tests passed ✓"
	@echo "=========================================="

test-py:
	@echo ""
	@echo "=== Python tests ==="
	$(PYTHON) -m unittest discover -s tests -v

test-c: vectors
	@echo ""
	@echo "=== C tests (host build, no ESP-IDF needed) ==="
	$(MAKE) -C $(VOLTHIUM_LIB) test

# The cross-validation test reads Python-encoded .bin files. Regen them
# if either the Python source or the vector generator has changed.
vectors: $(VOLTHIUM_LIB)/test_vectors/expected.txt

$(VOLTHIUM_LIB)/test_vectors/expected.txt: scripts/gen_test_vectors.py volthium/wire_protocol.py
	@echo ""
	@echo "=== regenerating test vectors ==="
	$(PYTHON) scripts/gen_test_vectors.py

clean:
	$(MAKE) -C $(VOLTHIUM_LIB) clean
	find . -name __pycache__ -type d -exec rm -rf {} +
