# Runbook — Volthium field operations

> The "if something's on fire, read this" doc. Everything you (or an AI agent
> with no memory of the project) need to operate the live system without
> re-deriving it. Last major update: 2026-07-01.

## Current deployment at a glance

| | |
|---|---|
| **Site** | The Barge Inn, Loon Lake |
| **Pack** | 2 × Volthium SC12200G4DPH 12V 200Ah LiFePO4 in series (24 V nominal) |
| **Reader** | Raspberry Pi 3B running Ubuntu 24.04 LTS aarch64 (kernel 6.8.0-1057-raspi) |
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
| `volthium-weekly-reboot.timer` | root | fires Sun 04:00 | clean-slate reboot to clear BlueZ / MMC state |

All four data services have `Restart=always`. If any crashes, systemd
respawns within a few seconds.

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
   adapters found" in the log):
   ```
   sudo systemctl restart bluetooth
   sudo hciconfig hci0 up
   sudo systemctl restart volthium-logger
   ```
4. **Adapter came back DOWN after `systemctl restart bluetooth`** — the
   `recover_adapter` code handles this now (verified 2026-07-01) but if a
   regression happened: `sudo bluetoothctl power on`.
5. **Logger dead** — `sudo systemctl restart volthium-logger`.
6. **Pi entirely unreachable via SSH** — power or SD card failure. Nothing
   software can do; needs physical access.

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

## Hardware upgrade plan (deferred)

The Pi 3B substrate is aging: SD card shows wear signatures (mmc_rescan hung
tasks), BT chip shares antenna with Wi-Fi. Software workarounds are keeping
things healthy but the root-cause fix is hardware.

Planned replacement, once parts arrive:
- **Raspberry Pi 4B** (any RAM tier ≥ 1 GB; workload uses ~300 MB)
- **USB Bluetooth 5.0 dongle** with RTL8761B chipset (TP-Link UB500 or
  equivalent) — the single most-important upgrade, gives independent BT
  antenna and modern controller
- **Samsung PRO Endurance 64 GB** microSD (or SanDisk HIGH ENDURANCE)
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
- `README.md` — project overview + local dev setup

## Recent milestones

| Date | What |
|---|---|
| 2026-06-18 | Cloud pipeline v1 (server + uploader + wire schema) |
| 2026-06-29 | Deployed to Railway |
| 2026-06-30 | Bring-up on Pi at cabin; discovered FM-2/3/5/8 series |
| 2026-07-01 | Write-load reduction (tmpfs); FM hardening (adapter power-on, direct BleakClient teardown, staleness alerts); preflight CI |
