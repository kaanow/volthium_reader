# `firmware/bms-link/` — battery-side ESP-IDF project

Cabin-side ESP32-S3 firmware: holds the BLE central role for both
Volthium BMSes, runs the time-to-X estimator (hybrid coulomb counter),
shifts between NORMAL / LOW / DEEP_SLEEP / HARD_CUT tiers per SOC, and
ships fused samples over RS-485 to the display-side board.

## Status

**Skeleton.** The CMakeLists, sdkconfig, and main.c + task stubs are
all in place. `app_main` creates the four FreeRTOS tasks documented in
`docs/firmware/architecture.md`. Each task currently just logs "STUB"
and waits — real implementation is TODO. The ble_task posts a
synthetic sample every 30 s so the rest of the pipeline (estimator +
encoder) can be exercised end-to-end without real BMSes on the bench.

When you build it now, you get a runnable ESP-IDF app that:
- initializes NVS
- spawns 4 tasks
- prints encoded wire frames (with sentinel/raw values) to the console
  every 30 s

That's enough to validate the linker pulls in volthium_lib correctly
and the shared types compile under both the host C11 toolchain (with
the standalone Makefile in `firmware/common/volthium_lib/`) and
ESP-IDF.

## Build

You need [ESP-IDF v5.x](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/get-started/index.html)
installed and sourced (`. $IDF_PATH/export.sh`).

```bash
cd firmware/bms-link
idf.py set-target esp32s3        # only first time
idf.py build
idf.py -p /dev/cu.usbserial-XXXX flash monitor
```

## Repo layout

```
firmware/
├── bms-link/                   ← THIS PROJECT
│   ├── CMakeLists.txt          top-level ESP-IDF project def
│   ├── sdkconfig.defaults      committed sdkconfig baseline
│   ├── main/
│   │   ├── CMakeLists.txt      component def
│   │   ├── main.h              shared types between tasks
│   │   ├── main.c              app_main + task creation
│   │   ├── ble_task.c          STUB — BLE central, BMS reads
│   │   ├── tx_task.c           STUB — RS-485 frame transmit
│   │   ├── power_task.c        STUB — SOC-tier state machine
│   │   └── adc_task.c          STUB — 24V rail voltage sense
│   └── ulp/                    (empty for now) — ULP voltage monitor
├── common/
│   └── volthium_lib/           shared C library (wire_protocol + estimator)
│       ├── CMakeLists.txt      ESP-IDF component manifest
│       ├── Makefile            host-side build for dev tests
│       └── ...
└── display/                    (not yet) — display-side project
```

## How the stubs are organized

Each `*_task.c` file:
1. Declares its task entry point in `main.h`.
2. The actual function in the .c file is a `while (true)` loop with a
   `vTaskDelay` and a `ESP_LOGI(... "STUB ...")` line.
3. The header comment lists the TODO checklist for that task — what
   needs to be implemented, which ESP-IDF subsystem it touches, and
   which design doc it references.

The skeleton is intentionally honest about being a skeleton — there
are no half-real implementations to confuse anyone. When work picks
up, each task gets its own focused commit.

## What needs implementing (rough order)

1. **ble_task** — biggest piece. Port the EJ BMS protocol decoder
   (`aiobmsble/ej_bms.py` → `firmware/common/volthium_lib/bms_decoder.{h,c}`),
   then NimBLE scan + connect + GATT + UART-service notify handler.
2. **tx_task** — straightforward once the wire frames have real fields.
   Driver setup is ESP-IDF boilerplate.
3. **power_task** — implement the 4-state machine from
   `docs/firmware/state_machine.md`. Mostly arithmetic on the estimator
   output.
4. **adc_task** — small. ADC oneshot + EMA + a getter.
5. **ulp/voltage_monitor.S** — ULP-RISC-V assembly. Replaces adc_task
   while in DEEP_SLEEP / HARD_CUT.
6. **NVS persistence** — estimator state, voltage-SOC table, hysteresis
   counter.

When you pick up the first piece, start with `ble_task` and the BMS
decoder — they unblock all downstream testing.
