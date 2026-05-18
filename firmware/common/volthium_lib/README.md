# `firmware/common/volthium_lib/`

Portable C library shared by both production firmware images
(`firmware/bms-link/`, `firmware/display/`) and validated against the
Python reference implementations in `volthium/`.

## What's in here

| File                            | Purpose                                              |
|---------------------------------|------------------------------------------------------|
| `wire_protocol.h` / `.c`        | 43-byte RS-485 frame format; encode/decode/CRC       |
| `estimator.h` / `.c`            | Time-to-X estimator (SOC-based + hybrid Ah-anchor)   |
| `test_wire_protocol.c`          | 22 unit cases for the wire protocol                  |
| `test_estimator.c`              | 17 unit cases for the estimator                      |
| `test_cross_validation.c`       | Python↔C cross-validation (4 reference frames)       |
| `test_vectors/*.bin`            | Python-encoded reference frames (committed)          |
| `Makefile`                      | Host build via clang/gcc; `make test` runs all 3     |
| `CMakeLists.txt`                | ESP-IDF component manifest                           |

## Design rules

1. **No `malloc` / dynamic allocation.** Estimator state lives in a
   caller-owned `volthium_estimator_t`. Wire-protocol structs live on
   the caller's stack. The firmware should never run the heap during
   normal operation.

2. **No ESP-IDF dependencies.** This library compiles cleanly with
   stock clang/gcc as well as `idf.py build`. That's why the tests
   run on a dev laptop — find bugs without flashing.

3. **Python is the spec.** When in doubt, the Python implementation
   in `volthium/wire_protocol.py` and `volthium/estimator.py` is the
   reference. `test_cross_validation.c` enforces this by asserting
   the C decoder matches the Python encoder byte-for-byte, and the
   C encoder produces bytes identical to the Python encoder for the
   same inputs.

4. **C11 + `-Wall -Wextra -Werror`.** Warnings break the build. The
   Makefile sets these flags.

## How firmware uses it

```c
#include "volthium_lib/wire_protocol.h"
#include "volthium_lib/estimator.h"

/* battery side */
volthium_estimator_t est;
volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
cfg.use_hybrid = true;
cfg.capacity_ah = 215.0f;
volthium_estimator_init(&est, &cfg);

/* on each new BLE sample */
volthium_sample_t s = { ... };          // filled from BMS reads
volthium_estimate_t e = volthium_estimator_update(&est, &s);

/* build a wire frame */
volthium_body_t body = { .seq = seq++, .state = (uint8_t)e.state, ... };
uint8_t wire[VOLTHIUM_FRAME_SIZE];
volthium_encode(&body, wire, sizeof(wire));
/* …send over UART RS-485… */
```

```c
/* display side */
volthium_body_t body;
if (volthium_decode(buf, len, &body) == VOLTHIUM_OK) {
    /* fields are populated; sentinel-aware accessors:
       if (volthium_u8_is_set(body.soc_a_pct)) { use it } */
}
```

## How to develop on a dev laptop

```bash
cd firmware/common/volthium_lib
make test    # builds and runs all three test programs
```

Or from the repo root:

```bash
make test    # runs Python AND C tests in one shot
```

The cross-validation test reads `test_vectors/*.bin` (Python-
encoded reference frames) and asserts:

1. C decoder of each Python-encoded frame produces field values
   matching the expected struct (21 fields per case).
2. C encoder of the same struct produces bytes BYTE-IDENTICAL to
   the Python file.

Both directions pass → the two implementations are bit-stable
against each other.

If a Python wire-protocol change is made, regenerate the vectors:

```bash
.venv/bin/python scripts/gen_test_vectors.py
```

(The top-level `make test` does this automatically when the Python
source is newer than the .bin files.)

## How ESP-IDF projects use it

Both `firmware/bms-link/CMakeLists.txt` and
`firmware/display/CMakeLists.txt` set:

```cmake
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_SOURCE_DIR}/../common")
```

before `include($ENV{IDF_PATH}/tools/cmake/project.cmake)`. ESP-IDF's
build system discovers `firmware/common/volthium_lib/CMakeLists.txt`
and treats it as a component. The component name (`volthium_lib`)
matches the directory.

Add it to a component's REQUIRES:

```cmake
idf_component_register(
    SRCS "main.c" ...
    INCLUDE_DIRS "."
    REQUIRES ... volthium_lib
)
```

## Testing invariants

- `sizeof(volthium_frame_t) == 43` — `_Static_assert` in
  `wire_protocol.h` enforces this at compile time across all builds.
- `sizeof(volthium_body_t) == 39` — same.
- CRC-16/CCITT-FALSE: `crc16("123456789") == 0x29B1` — the canonical
  test vector. Both the C `volthium_crc16_ccitt()` and the Python
  `crc16_ccitt()` produce this.

## When to change the wire format

1. Bump `VOLTHIUM_VERSION` in `wire_protocol.h` AND
   `volthium/wire_protocol.py`.
2. Update both implementations (struct layout, field sizes, encode
   / decode logic).
3. Update `tests/test_wire_protocol.py` AND
   `test_wire_protocol.c` with new expected sizes / vectors.
4. Update `scripts/gen_test_vectors.py` so the cross-validation
   .bin files regenerate.
5. Run `make test` from the repo root — everything must still pass.
6. Document the change in `docs/firmware/architecture.md` § "RS-485
   framing" and the version bump rationale.

## Cross-references

- [`docs/firmware/architecture.md`](../../../docs/firmware/architecture.md) —
  big-picture firmware design
- [`docs/firmware/state_machine.md`](../../../docs/firmware/state_machine.md) —
  the SOC-tier state machine
- [`docs/firmware/ble_flap_recovery.md`](../../../docs/firmware/ble_flap_recovery.md) —
  observed BLE flap behavior + firmware retry policy
- [`docs/hardware/bms_calibration.md`](../../../docs/hardware/bms_calibration.md) —
  why the estimator defaults to hybrid mode + `capacity_ah=215`
- [`volthium/wire_protocol.py`](../../../volthium/wire_protocol.py) —
  Python reference
- [`volthium/estimator.py`](../../../volthium/estimator.py) —
  Python reference
