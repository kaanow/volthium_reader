# Runbook — Volthium field operations

> The "if something's on fire, read this" doc. Everything you (or an AI agent
> with no memory of the project) need to operate the live system without
> re-deriving it. Last major update: 2026-07-01.

## Current deployment at a glance

| | |
|---|---|
| **Site** | The Barge Inn, Loon Lake |
| **Pack** | 2 × Volthium SC12200G4DPH 12V 200Ah LiFePO4 in series (24 V nominal) |
| **Reader** | Raspberry Pi 3B running Ubuntu 24.04 LTS aarch64 (kernel 6.8.0-1060-raspi) |
| **BLE adapter** | TP-Link UB500 USB dongle (RTL8761B chipset), enumerates as `hci1` — the internal BCM43438 (`hci0`) is left DOWN, its UART bring-up is broken on this board |
| **Storage** | Samsung PRO Endurance 64 GB microSD (replaced the aging SU16G on 2026-07-09) |
| **Reader hostname / IP** | `kwpi` / `192.168.1.251` (LAN + ZeroTier reachable) |
| **SSH access** | `ssh kaan@192.168.1.251` — key auth, passwordless sudo |
| **Repo on Pi** | `/srv/volthium_reader` (branch `main`, owner `claude:users`) |
| **Venv on Pi** | `/srv/volthium_reader/.venv` (Python 3.12 from Ubuntu) |
| **Cloud (production)** | https://volts.alti2.de |
| **Cloud (Railway-provided)** | https://volthiumreader-production.up.railway.app |
| **Deploys from** | `main` branch on `git@github.com:kaanow/volthium_reader.git` (auto) |
| **Alerting** | ntfy.sh push notification (topic value: operator's password manager) |
| **Source-of-truth clone (dev / research)** | `/Users/pivot/Documents/repo/volthium_sw/volthium_reader/` on operator's Mac |
| **⚠ do-not-touch clone** | `/Users/pivot/Documents/repo/volthium_reader/` — that's the *hardware* workstream, on a different branch |

## Architecture in 60 seconds

1. **`volthium-logger`** on the Pi reads both batteries over BLE every 10 s.
   Writes to `data/pack.csv` (durable) and `/run/volthium/ble_events.jsonl`
   (tmpfs — sealed-segment rotation).
2. **`volthium-uploader`** tails `data/pack.csv`, converts naive-local to
   UTC `Z`, POSTs batches to Railway `/ingest`, upserts on `(source_id, ts)`.
3. **`volthium-events-uploader`** drains sealed segments from tmpfs to
   Railway `/api/events/ingest` → `ble_events` table.
4. **`volthium-dashboard`** on the Pi serves the local dashboard at :8421.
5. **Railway** hosts the FastAPI ingest server + a public browser dashboard
   at the URL above. Postgres retains everything indefinitely.
6. **Staleness monitor** (on Railway) polls every 60 s; fires ntfy push on
   `fresh → stale` (>5 min silence) and `stale → fresh` recovery.

Deep architecture: `docs/cloud_architecture.md`. Deep field notes:
`docs/reliability_failure_modes.md`.

## Where things live on the Pi

| Path | What |
|---|---|
| `/srv/volthium_reader/` | Repo checkout; services run from here |
| `/srv/volthium_reader/data/pack.csv` | Durable readings log (survives reboot) |
| `/srv/volthium_reader/data/pack.log` | Human-readable logger progress |
| `/srv/volthium_reader/pack.env` | Battery BLE addresses (`ADDR_A_LINUX`, `ADDR_B_LINUX`) |
| `/etc/volthium-uploader.env` | `READER_TOKEN` (bearer for Railway) |
| `/etc/systemd/system/volthium-*.service` | Unit files |
| `/etc/systemd/system/volthium-*.service.d/*.conf` | Local drop-in overrides |
| `/etc/tmpfiles.d/volthium.conf` | Ensures `/run/volthium/` exists at boot |
| `/run/volthium/` | tmpfs; event log + sealed segments + uploader.log |

## Systemd services on the Pi

| Unit | User | Runtime cost | Purpose |
|---|---|---|---|
| `volthium-logger.service` | claude | one Python process, ~30 MB RSS | polls BLE every 10 s, writes CSV + events |
| `volthium-uploader.service` | claude | one Python process, ~25 MB RSS | POSTs pack.csv rows to Railway |
| `volthium-events-uploader.service` | claude | one Python process, ~20 MB RSS | POSTs sealed event segments to Railway |
| `volthium-dashboard.service` | claude | one Python process, ~40 MB RSS | local browser dashboard on :8421 |
| `volthium-weekly-reboot.timer` | root | fires 1st Sun of month, 04:00 | clean-slate reboot to clear BlueZ / MMC state (used to be weekly; monthly since 2026-07-09 hardware refresh) |

All four data services have `Restart=always`. If any crashes, systemd
respawns within a few seconds.

## Env vars on the Pi (logger drop-in)

`/etc/systemd/system/volthium-logger.service.d/10-tmpfs-events.conf`:

| Var | Purpose |
|---|---|
| `VOLTHIUM_BLE_EVENT_LOG` | Path to tmpfs event log (sealed-segment rotation lives here) |
| `VOLTHIUM_ADAPTER` | BLE controller pin — accepts a MAC or `hci*` name. Set to the UB500's BD address `20:E1:5D:68:30:8B`. Resolved to `hci*` at process start via `hciconfig`; emits `adapter_pinned` event to prove it took effect |
| `VOLTHIUM_CAPTURE_RAW` | (off in prod) When `1`, tap raw BLE notify frames into the event log for lab replay. Turned off 2026-07-09 — the [`data/simulator/`](../data/simulator/) corpus is enough for now |

## Env vars on Railway

Set in the service's **Variables** tab in the Railway dashboard.

| Var | Purpose | Default if unset |
|---|---|---|
| `DATABASE_URL` | Postgres URL, injected by the Postgres plugin | (required) |
| `READER_TOKEN_PI_BARGE` | bearer token for source_id=pi-barge | (required) |
| `STALENESS_WEBHOOK_URL` | ntfy push endpoint; alerting disabled if empty | empty |
| `STALENESS_THRESHOLD_S` | seconds of silence before "stale" | 300 |
| `STALENESS_CHECK_INTERVAL_S` | poll interval | 60 |
| `EMA_ALPHA` / `CAPACITY_AH` / `FLOOR_PCT` / `CEILING_PCT` / `IDLE_CURRENT_A` | estimator tunables | see `cloud/server/config.py` |
| `DB_MIGRATE` | if truthy, apply migrations at startup | `1` |
| `DISPLAY_TZ` | dashboard render zone | `America/Toronto` |

Env-var naming rule for reader tokens: `READER_TOKEN_<UPPER_SNAKE>` grants
`source_id=<lower-kebab>`. So `READER_TOKEN_PI_BARGE` ↔ `pi-barge`.

## Quick health check (30 seconds)

From anywhere:
```
curl https://volts.alti2.de/healthz              # expect: "ok"
curl https://volts.alti2.de/api/latest           # expect: ts within the last minute
```

Or open https://volts.alti2.de/ in a browser — if the timestamp on the
dashboard is recent and both batteries show data, you're good.

From SSH:
```
sudo systemctl is-active volthium-logger volthium-uploader volthium-events-uploader volthium-dashboard
# expect four "active"
sudo journalctl -u volthium-logger -n 20 --no-pager
```

## Common ops

### Restart one service
```
sudo systemctl restart volthium-logger
sudo systemctl status  volthium-logger --no-pager -l
```

### Restart the whole BLE stack (fixes most transient issues)
```
sudo systemctl restart bluetooth
sudo hciconfig hci0 up
sudo systemctl restart volthium-logger
```

### Deploy a code change to Railway
1. Local: `make preflight` (needs Docker; skips if you don't).
2. `git push origin main` — Railway auto-deploys, ~1 min.
3. Verify: `curl https://volts.alti2.de/healthz` still returns `ok`.
4. GitHub Actions runs the same preflight in CI on every push touching
   `cloud/server/**` or `cloud/shared/**` — that's the guardrail.

### Deploy a code change to the Pi
```
ssh kaan@192.168.1.251
cd /srv/volthium_reader
sudo -u claude git pull --ff-only origin main
sudo systemctl restart volthium-logger volthium-uploader volthium-events-uploader
```

### View Postgres readings
```
railway run psql $DATABASE_URL   # in the Railway CLI, from the linked project
# or from local:
railway shell
psql $DATABASE_URL -c "SELECT ts, state, pack_v, soc_a, soc_b FROM readings ORDER BY ts DESC LIMIT 20;"
```

## Push notifications you might receive

All go to the same ntfy topic (env var `STALENESS_WEBHOOK_URL` on Railway).

| Title | What it means | First move |
|---|---|---|
| `pi-barge stale` | No fresh telemetry for 5+ min | See "stale push" playbook below |
| `pi-barge recovered` | Telemetry flowing again after stale | No action; sanity-check on dashboard |
| `pi-barge adapter pin failing` | Reader's pinned adapter (UB500) is unresolvable; it's silently falling back to the internal chip. Payload names the fallback BD address. | Not urgent — internal chip usually works. Plan a physical unplug/replug of the UB500 next time you're at the Pi. |
| `pi-barge adapter re-pinned` | Fallback recovered; pinned adapter is back | No action |
| `pi-barge wedge L2 — <classification>` | BLE stack wedged badly enough that a plain HCI reset didn't fix it. The classification tells you which layer: `kernel_usb_reset_chip_hung`, `chip_firmware_hci_unresponsive`, `bluez_discovery_state_stuck`, `bluez_adapter_object_missing`, `bms_peer_not_responding`, `power_under_voltage_active`, etc. | Cross-reference the classification with the wedge_snapshot event on Railway (has full evidence: dmesg tail, hciconfig, bluetoothctl show, vcgencmd throttled, temp). Response depends on which layer. |

Wedges at recovery-ladder Level 1 self-heal within a few seconds and don't push — the process-exit Level 3 usually resolves the stragglers via systemd's `Restart=always`.

## Failure modes and response

### "Volthium: pi-barge stale" push arrives
1. **Wait 30 min.** Most transient failures self-resolve — restart-on-wedge,
   adapter-recovery ladder, `Restart=always`. If a "recovered" push arrives,
   ignore.
2. **Still stale** → SSH in:
   ```
   ssh kaan@192.168.1.251
   sudo journalctl -u volthium-logger --since '30 min ago' | tail -80
   ```
3. **BlueZ wedged** (see `org.bluez.Error.InProgress` or "No powered Bluetooth
   adapters found" in the log). First look up which hci* the UB500 lives
   on this boot (it can vary), then reset that specific one:
   ```
   hciconfig | awk '/^hci/{h=$1} /20:E1:5D:68:30:8B/{sub(":","",h); print h}'
   sudo systemctl restart bluetooth
   sudo hciconfig <hci_from_above> up
   sudo systemctl restart volthium-logger
   ```
4. **Adapter came back DOWN after `systemctl restart bluetooth`** — the
   `recover_adapter` code handles this now (verified 2026-07-01) but if a
   regression happened: `sudo bluetoothctl power on`.
   The reader is pinned to the UB500 by BD address (`VOLTHIUM_ADAPTER=20:E1:5D:68:30:8B`
   in the logger drop-in), so whichever `hci*` index the dongle enumerates as,
   the scanner picks it. If the dongle physically disappears (unplugged /
   USB fault) the pin resolution fails, an `adapter_pin_failed` event fires,
   and the code falls back to bleak's default adapter — which will try the
   flaky internal chip. Plug the dongle back in.
5. **Logger dead** — `sudo systemctl restart volthium-logger`.
6. **Pi entirely unreachable via SSH** — power or SD card failure. Nothing
   software can do; needs physical access.

### "adapter pin failing" push arrives (no matching stale)
The UB500 has stopped responding — data is still flowing on the internal BT.
Not urgent, but the internal BT is less reliable, so the situation should be
resolved. Steps:

1. Check the Railway event stream:
   ```
   curl https://volts.alti2.de/api/events?event=adapter_fallback&limit=1
   ```
   The `fallback_hci` field tells you which adapter is now serving reads.
2. SSH in and look at the UB500's state:
   ```
   ssh kaan@192.168.1.251
   hciconfig | grep -B1 "20:E1:5D:68:30:8B"     # find the UB500's hci*
   sudo hciconfig hci<N> up
   ```
   If the `up` command returns `Connection timed out (110)`, the chip is
   firmware-hung — a plain `hciconfig up` won't revive it. Only a physical
   unplug/replug will.
3. **Physical unplug/replug** of the UB500 dongle at the Pi. Takes seconds;
   the logger picks it up on its next `_adapter_kwargs()` call after the
   next process restart (or restart it manually with
   `sudo systemctl restart volthium-logger` to fast-forward).

### "wedge L2 / L3" push arrives
The classification in the title is the fast triage. Then pull the full
snapshot from Railway to see the raw evidence:

```
curl "https://volts.alti2.de/api/events?event=wedge_snapshot&limit=1" | jq .
```

Common classifications and what they mean:

| Classification | Layer | Likely fix |
|---|---|---|
| `kernel_usb_reset_chip_hung` | Kernel had to USB-reset the dongle because it stopped answering | Chip firmware hung; usually recovers on its own via kernel reset. Watch for repeats. |
| `chip_firmware_hci_unresponsive` | Same but kernel hasn't given up yet | Ditto. If it doesn't self-recover in ~2 min, unplug/replug the dongle. |
| `power_under_voltage_active` | Pi throttled register shows active undervoltage | PSU / cable issue. Check the power supply. |
| `bluez_discovery_state_stuck` | FM-3 classic; bluetoothd's Discovering flag stuck | Recovery ladder Level 2 (bluetoothd restart) usually clears this |
| `bluez_adapter_object_missing` | D-Bus adapter object disappeared, but chip is fine | Ditto |
| `ub500_dongle_missing_from_usb` | lsusb doesn't see the dongle | Physical unplug — plug it back in |
| `bms_peer_not_responding` | Adapter fine, BMS not answering | RF / BMS-side issue, not our stack. Usually self-resolves. |

### No pushes for weeks
Two possibilities: everything is normal (fine), or the alerting itself broke
(bad). Every ~2 weeks, do the 30-second health check above.

### Sudden "no data yet" on the dashboard
- Fresh Railway deploy that lost Postgres state? Unlikely (Postgres is a
  managed add-on) but worth checking Railway's UI.
- More likely: check that the Pi's uploader is still posting; if it hasn't
  posted in a while, alerts should have fired.

### Uploader keeps getting 502 from Railway
- Railway app is crash-looping. Check GitHub Actions for a failed preflight
  on the last push. Check Railway deploy logs for a Python traceback.
- Fastest fix: `git revert <bad commit> && git push origin main` — Railway
  redeploys the previous good commit within ~1 min.

## Hardware upgrade plan (partially completed)

Done 2026-07-09:
- **Samsung PRO Endurance 64 GB** microSD — old SU16G was showing wear
  signatures (mmc_rescan hung tasks). Imaged old → new, root grew to 59 GB.
- **TP-Link UB500** USB BT dongle (RTL8761B, BT 5.1). The built-in
  BCM43438 (`hci0`) on the imaged card would not come up — firmware loaded
  but every subsequent HCI command timed out (classic Pi 3B miniUART
  clock instability, likely lost the `dtoverlay=miniuart-bt` overlay
  from the old card's config.txt during imaging). Rather than edit
  `/boot/firmware/config.txt` remotely — one bad line bricks the Pi until
  someone visits the cabin — we plugged in the UB500. It enumerated as
  `hci1`, BlueZ preferred it (UP over DOWN), the logger picked it up on
  its own, live readings resumed within ~10 s of insertion.

Still deferred:
- **Raspberry Pi 4B** (any RAM tier ≥ 1 GB; workload uses ~300 MB)
- Official Pi 4 USB-C PSU, case with active cooling
- Optional: USB 3.0 SSD to escape SD cards entirely (Pi 4 boots from USB
  natively)

Migration path: **parallel-Pi** — prep the new box at desk, verify BLE
reads work, physical swap at the cabin. Zero cabin downtime.

Every current workaround that exists *because* of the Pi 3B is tagged
`HARDWARE-DEP: Pi 3B ...` in the source — `grep -rn HARDWARE-DEP` finds
them all, and `docs/reliability_failure_modes.md` § "Once hardware is
upgraded" enumerates them by file.

## Related docs

- `docs/cloud_architecture.md` — cloud + wire protocol + env vars + deploy
- `docs/reliability_failure_modes.md` — FM-* field log; root causes and fixes
- `docs/production_design.md` — original hardware design (ESP32 target)
- `data/simulator/README.md` — captured raw BMS frame corpus for building an offline simulator
- `README.md` — project overview + local dev setup

## Recent milestones

| Date | What |
|---|---|
| 2026-06-18 | Cloud pipeline v1 (server + uploader + wire schema) |
| 2026-06-29 | Deployed to Railway |
| 2026-06-30 | Bring-up on Pi at cabin; discovered FM-2/3/5/8 series |
| 2026-07-01 | Write-load reduction (tmpfs); FM hardening (adapter power-on, direct BleakClient teardown, staleness alerts); preflight CI |
| 2026-07-09 | SD card replaced (SU16G → Samsung PRO Endurance 64 GB); built-in BT wedged after imaging; UB500 dongle plugged in, live readings resumed on `hci1` |
| 2026-07-09 | Hardware-refresh cleanup: `VOLTHIUM_ADAPTER` pin (MAC-based), raw-frame corpus archived to `data/simulator/`, capture off in prod, reboot cadence weekly → monthly, HARDWARE-DEP markers refreshed |
