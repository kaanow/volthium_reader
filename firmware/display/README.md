# `firmware/display/` — kitchen display-side ESP-IDF project

Receives RS-485 frames from the battery-side board and drives the
4.2" tri-color e-paper panel mounted in the kitchen wall plate.
Three buttons, a watchdog for link-down detection, and a "release
BLE" back-channel to the battery side.

## Status

**Skeleton.** Same shape as `firmware/bms-link/`: CMakeLists +
sdkconfig.defaults + main.c with FreeRTOS task creation + 4 task stubs
(`rx_task`, `render_task`, `input_task`, `watchdog_task`), each with
a header comment listing the implementation TODO checklist.

The `rx_task` stub posts a synthetic frame every 30 s so the e-paper
rendering path can be developed end-to-end without an actual RS-485
link.

## Differences from `bms-link/`

- **No Bluetooth** — `CONFIG_BT_ENABLED=n` in sdkconfig.defaults.
- **No MOSFET load-switch** — display-side stays alive longer than
  battery-side per `docs/firmware/state_machine.md`.
- **No ULP** — display side doesn't sleep that deeply; it just light-
  sleeps between e-paper refreshes.
- **SPI bus to the e-paper** instead of BLE central.
- **Three buttons** instead of one override.

## Build

```bash
cd firmware/display
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/cu.usbserial-XXXX flash monitor
```

(Same ESP-IDF v5.x prerequisite as `bms-link/`.)

## Layout

```
firmware/display/
├── CMakeLists.txt           top-level ESP-IDF project
├── sdkconfig.defaults
├── .gitignore
├── README.md
└── main/
    ├── CMakeLists.txt
    ├── main.h               shared types + task entry decls
    ├── main.c               app_main + task creation
    ├── rx_task.c            STUB — RS-485 RX, decode wire frames
    ├── render_task.c        STUB — e-paper renderer
    ├── input_task.c         STUB — 3 buttons, debounce, long-press
    └── watchdog_task.c      STUB — link-down detection + overlays
```

## What needs implementing (rough order)

1. **render_task + e-paper driver** — biggest piece. Brings up the
   Waveshare 4.2" panel via SPI. Adapt one of the existing ESP-IDF
   community components or roll our own from the panel datasheet.
2. **rx_task** — UART driver setup + the framing loop. Decoder is
   already done (`volthium_decode()` in volthium_lib).
3. **input_task** — debounced button reads with long-press detection.
4. **watchdog_task** — small; mostly an `esp_timer` periodic that
   checks `received_ms` against now.
5. **Back-channel for release-BLE button** — minimal wire-protocol
   extension or a separate small command frame. Design pending.
