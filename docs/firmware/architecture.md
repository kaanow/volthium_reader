# Firmware architecture

Two ESP32-S3 firmwares sharing a common-code library. Both built with
ESP-IDF (not Arduino — we want fine-grained light/deep sleep control and
proper FreeRTOS tasking).

## Repo layout (proposed)

```
firmware/
├── common/                 # shared between both nodes
│   ├── volthium_lib/
│   │   ├── ej_bms.{h,c}         # port of volthium/pack.py BMS decoder
│   │   ├── estimator.{h,c}      # port of volthium/estimator.py
│   │   ├── wire_protocol.{h,c}  # port of volthium/wire_protocol.py
│   │   └── crc16.{h,c}
│   └── components/
├── bms-link/               # battery-side firmware (ESP-IDF app)
│   ├── main/
│   │   ├── main.c               # FreeRTOS task setup
│   │   ├── ble_task.c           # BLE central, BMS reads
│   │   ├── tx_task.c            # RS-485 frame transmit
│   │   ├── power_task.c         # SOC-tier state machine, ULP, MOSFET ctrl
│   │   └── adc_task.c           # 24V sense
│   ├── ulp/
│   │   └── voltage_monitor.S    # ULP-RISC-V routine for hard-cut state
│   ├── partitions.csv
│   ├── sdkconfig.defaults
│   └── CMakeLists.txt
└── display/                # display-side firmware (ESP-IDF app)
    ├── main/
    │   ├── main.c
    │   ├── rx_task.c            # RS-485 frame receive + decode
    │   ├── render_task.c        # e-paper rendering
    │   ├── input_task.c         # button handling
    │   └── ble_release.c        # button → RS-485 release command
    ├── components/
    │   └── epd_4in2b_v2/        # Waveshare driver (well-documented)
    ├── partitions.csv
    ├── sdkconfig.defaults
    └── CMakeLists.txt
```

## Battery-side tasks (FreeRTOS)

| Task            | Priority | Period / event                | Notes                                      |
|-----------------|----------|-------------------------------|--------------------------------------------|
| `ble_task`      | 5        | event-driven; runs while connected | Holds persistent BLE central to both BMS. Handles polite-disconnect on `release` event from RS-485. |
| `tx_task`       | 4        | every 30 s (state 1) / 60 s (state 2) | Builds WireFrame from latest BLE samples, emits RS-485 frame |
| `power_task`    | 6        | every 5 s + on SOC threshold crossings | Implements the 4-tier state machine; commands MOSFET; manages light/deep sleep |
| `adc_task`      | 3        | every 2 s                     | Reads 24V sense; provides voltage-based SOC fallback when BLE is down |
| `cli_task`      | 2        | USB serial available          | Optional debug shell over USB-OTG |

Inter-task communication: FreeRTOS queues with the latest `BMSSample`,
`PackReading`, and `Estimate` structs. Queue depth of 1 (mailbox style)
because newer readings supersede older ones.

## Display-side tasks

| Task            | Priority | Period / event                | Notes                                      |
|-----------------|----------|-------------------------------|--------------------------------------------|
| `rx_task`       | 5        | RS-485 frame arrived          | Validates CRC, parses WireFrame, posts to render queue |
| `render_task`   | 4        | on new frame OR button press OR 30 s tick | Decides what to draw, kicks e-paper |
| `input_task`    | 3        | GPIO interrupts (debounced)   | Maps buttons to events; sends "release BLE" over RS-485 |
| `watchdog_task` | 2        | every 10 s                    | If no frame in 90 s, draws "LINK DOWN" overlay |

## State machine (battery-side `power_task`)

Formal spec with hysteresis tables and SOC-source rules per state is
in **[`docs/firmware/state_machine.md`](state_machine.md)**. Diagram
inlined below for orientation:


```
            ┌──────────┐
            │  NORMAL  │  (>25%)  ── persistent BLE, 30s tx
            └────┬─────┘
                 │ SOC ≤ 25 % for 1 s
                 ▼
            ┌──────────┐
            │   LOW    │  (15-25%)  ── 60s tx, "LOW PACK" flag
            └────┬─────┘
                 │ SOC ≤ 15 % for 1 s    │ SOC ≥ 27 % for 2 min
                 ▼                        ▲
            ┌──────────┐                  │
            │ DEEPSLEEP│  (10-15%)        │
            └────┬─────┘  ── BLE disconnect, ULP wake 10 min
                 │ SOC ≤ 10 %    │ ULP-read SOC ≥ 18 % for 2 consec wakes
                 ▼                ▲
            ┌──────────┐          │
            │ HARDCUT  │          │
            └──────────┘──────────┘
              ULP only; MOSFET off
              wake on ULP voltage threshold or override-button
```

Hysteresis on up-transitions (2 min sustained above the threshold)
prevents flapping when load cycles.

## RS-485 framing (already specified)

See `volthium/wire_protocol.py` (Python reference impl) and
`tests/test_wire_protocol.py` for vectors. C port in
`firmware/common/volthium_lib/wire_protocol.{h,c}` will match byte-for-byte.

CRC-16/CCITT-FALSE test vector: `"123456789"` → `0x29B1`.

## Estimator port

The Python `Estimator` (in `volthium/estimator.py`) is ~80 lines of
arithmetic + a `deque(maxlen=20)`. Direct C port: a ring buffer plus
two EMA accumulators. State persists across deep-sleep via NVS so we
don't reset the smoothing when waking.

## OTA strategy

ESP32-S3 has dual app partitions. Two paths:

1. **USB-C dev port** behind the battery enclosure lid — manually flash
   when the user opens the box. Simplest, manageable for a once-a-year
   update cadence.
2. **Wi-Fi via display-side** — display side enables a temporary Wi-Fi
   AP when both buttons are held (or a hidden menu sequence). User
   browses to it, uploads firmware. Display side validates and pushes
   the new image to battery side over RS-485 in 256-byte chunks.

Recommend path 1 for v1; path 2 as a v2 feature if updates become
frequent.

## Debug visibility

Each board exposes a 4-pin debug header on the PCB:

| Pin | Net           | Purpose                                   |
|-----|---------------|-------------------------------------------|
| 1   | GND           |                                           |
| 2   | UART0_TX      | ESP-IDF console (firmware logs)           |
| 3   | UART0_RX      | "                                         |
| 4   | RESET#        | for emergency reset / reflashing          |

Use any FTDI cable. The console runs at 115200 8N1.

Optional onboard LED on GPIO15 (battery side) — slow blink in NORMAL,
fast in LOW, off in DEEPSLEEP/HARDCUT, solid during BLE connect attempts.
