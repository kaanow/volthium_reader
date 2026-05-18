# Volthium 24V Pack Reader

Reads the state of two Volthium **SC12200G4DPH** 12V 200Ah LiFePO4 batteries
wired in series (24V system, "The Barge Inn"), and shows a live estimate of
time-to-full when charging or time-to-empty (to 10% SOC) when discharging.

This repo is the **dev/validation rig** — it runs on a Mac laptop using its
built-in Bluetooth. Once the readings line up with the Volthium phone app and
the time estimator is dialed in, we plan a second, low-power hardware target
for permanent install in the cabin.

## How it works

The Volthium SC12200G4DPH BLE protocol matches the **E&J Technology BMS**
family — same Nordic UART service, same `:...~` ASCII-hex frames. We use
[`aiobmsble`](https://github.com/patman15/aiobmsble), which already decodes
that protocol, and combine the two single-battery samples into one logical
24V pack reading.

For a series pack:
- pack voltage = `V_a + V_b` (≈ 26V fully charged, ≈ 24V nominal)
- pack current = same through both batteries (we average to suppress noise)
- **charging** finishes when the *higher-SOC* battery hits 100%
- **discharging** finishes when the *lower-SOC* battery hits the floor

The estimator uses an exponential moving average on current so the displayed
"3h 20m" doesn't flicker every time a cloud passes or the inverter steps load.

## Setup

```bash
brew install python@3.13        # only if not already installed
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

macOS will prompt for Bluetooth permission the first time the Terminal app
tries to scan. Approve it under *System Settings → Privacy & Security → Bluetooth*.

## Use

### 1. Find the batteries

```bash
.venv/bin/python scripts/scan.py
```

Both batteries advertise as `V-12V200Ah-<serial>`. Note their BLE addresses.
(Tip: temporarily power one off if you can't tell A from B.)

### 2. Smoke test — one reading

```bash
.venv/bin/python scripts/read_once.py --a AA:BB:CC:DD:EE:FF --b 11:22:33:44:55:66
```

Cross-check the SOC, voltage and current against the Volthium app. If they
match, the protocol is decoded correctly.

### 3. Live dashboard

```bash
.venv/bin/python scripts/monitor.py \
    --a AA:BB:CC:DD:EE:FF \
    --b 11:22:33:44:55:66 \
    --interval 5 \
    --csv pack.csv
```

`--csv` is optional but recommended for the validation phase — we want
real charge/discharge curves to tune the smoothing constant.

### Easiest way to launch (for anyone, no Terminal needed)

Double-click **Volthium Monitor** on the Desktop. It silently starts the
logger + dashboard if they aren't already running, opens the dashboard
in your default browser, and shows a notification with the LAN URL to
share with phones on the same Wi-Fi.

If the Desktop alias gets deleted, recreate it with:

```bash
./scripts/install_desktop_launcher.sh
```

The .app bundle lives at `Volthium Monitor.app/` in the repo root; the
Desktop alias just points at it, so any future improvements to the .app
are picked up automatically.

### 4. Headless logger + browser dashboard

For long unattended runs, the rich-TUI `monitor.py` isn't ideal — it needs a
visible terminal. Use these two together instead:

```bash
# In one terminal — keep alive with `caffeinate -i` so the Mac doesn't doze.
caffeinate -i .venv/bin/python scripts/log.py \
    --a 9058AE7F-F98B-D0F6-237D-6769894DE118 \
    --b 6EC69980-CA43-7DEF-519B-6235C8C535B7 \
    --interval 10 \
    --csv data/pack.csv --log data/pack.log

# In another terminal:
.venv/bin/python scripts/dashboard.py --csv data/pack.csv
# then open http://localhost:8421/
```

The logger never gives up — it backs off and retries on BLE errors. The
dashboard is read-only off the CSV, so both can run forever.

## Files

- `volthium/pack.py` — discovery + `BatteryReading` / `PackReading`
- `volthium/estimator.py` — smoothed time-to-full / time-to-empty
- `scripts/scan.py` — find the batteries
- `scripts/read_once.py` — single-shot smoke test
- `scripts/monitor.py` — live rich-TUI dashboard (one-shot use)
- `scripts/log.py` — headless CSV logger (for unattended runs)
- `scripts/dashboard.py` — browser dashboard (binds LAN by default)
- `scripts/install_desktop_launcher.sh` — re-create the Desktop alias
- `Volthium Monitor.app/` — double-clickable launcher
- `Launch Volthium Monitor.command` — Terminal-friendly launcher with QR code
- `docs/production_design.md` — architecture for the cabin-side hardware
- `data/pack.csv`, `data/pack.log` — captured data (gitignored)

## Known limits / open questions

- The Volthium app and our reader **cannot both be connected at once** — the
  BLE peripheral only accepts one central. Close the app before running.
- Capacity defaults to 200 Ah per battery. Override with `--capacity` if the
  batteries have aged.
- The 10% "empty" floor is configurable via `--floor`.
- Range was specified as ~6 m by Volthium; the cabin install will need either
  a closer-range MCU near the batteries or a Bluetooth proxy.
