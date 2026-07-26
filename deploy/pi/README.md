# Pi-side system config (versioned)

Everything the reader Pi (`kwpi`) needs outside the repo checkout itself —
systemd units, drop-ins, udev rules — so `/etc` state is reproducible instead
of hand-rolled. Before 2026-07-13 these lived only on the Pi.

## Install / update

```
ssh kaan@192.168.1.251
cd /srv/volthium_reader
sudo -u claude git pull --ff-only origin main
sudo bash deploy/pi/install.sh
```

`install.sh` is idempotent: copies configs, reloads systemd + udev, applies
the UB500 autosuspend override to the live device, archives a stale
pre-tmpfs `data/ble_events.jsonl` once, and restarts the three data services.
It never touches network, ZeroTier, or boot config.

## What's here and why

| File | Purpose |
|---|---|
| `systemd/volthium-logger.service` | BLE logger unit (unchanged from the hand-rolled one) |
| `systemd/volthium-logger.service.d/10-reader-env.conf` | Reader env: event log on `data/` (durable), UB500 pin, **internal-BT fallback**, replug USB ID |
| `systemd/volthium-uploader.service` | pack.csv → Railway (logs to `data/`, not tmpfs) |
| `systemd/volthium-events-uploader.service` | sealed event segments → Railway (drains `data/`, not tmpfs) |
| `udev/50-volthium-ub500-usb-power.rules` | **Disables USB autosuspend for the UB500** — the root-cause fix for the FM-9 firmware hangs |

## Transport: RS485 primary, BLE dormant fallback (2026-07-26)

Telemetry now comes over **wired RS485** (`volthium-rs485-logger.service`),
which sidesteps the whole BLE dormancy/wedge failure class. The BLE logger
(`volthium-logger.service`) is **disabled but intact** — a latent fallback, not
deleted. `Conflicts=volthium-logger.service` on the RS485 unit guarantees the
two never run at once, so the flip is a clean two-liner.

**If an RS485 adapter dies — fall back to BLE:**
```
sudo systemctl disable --now volthium-rs485-logger
sudo systemctl enable  --now volthium-logger
```

**Back to the wired primary:**
```
sudo systemctl disable --now volthium-logger
sudo systemctl enable  --now volthium-rs485-logger
```

Both write the identical `pack.csv` → the same uploader → Railway, so the flip
is transparent downstream (the only visible tell is `read_ok`'s `transport`
field flipping between `rs485` and `ble`, which `scripts/status_check.py` now
surfaces). Also running: `volthium-xanbus-capture` and `volthium-modbus-poll`
(Insight Home decode — see `docs/xanbus-decode.md`).

## tmpfs retirement (2026-07-13)

The `/run/volthium` tmpfs existed for the old SU16G SD card's write-rate
limits. With the Samsung PRO Endurance card (2026-07-09) that constraint is
gone, and the 2026-07-12/13 outage showed the cost of volatile diagnostics:
evidence that doesn't survive reboots/crash-loops can't be shipped or studied.
Event log, uploader log, and sealed segments now all live in `data/`.
`/etc/tmpfiles.d/volthium.conf` is left in place (an empty tmpfs dir is
harmless) so nothing here risks boot-time behavior; remove it at leisure.

The dashboard unit is unchanged and not duplicated here (no local config).
`/etc/volthium-uploader.env` (bearer token) is a secret — never in git.
