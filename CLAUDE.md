# Operating rules — READ FIRST

These are hard rules, not suggestions. They were written after an avoidable
production outage (2026-07-26): a heavy analysis job (`xanbus_decode.py`) was run
directly on the barge Pi, exhausted its 1 GB of RAM, hung the box, and took
telemetry + SSH down. Nobody visits the site for weeks, so a crash is not a blip
— it is weeks of lost data. Do not let it happen again.

## The single most important fact

**The barge Pi (`kwpi`) is a 1 GB Pi 3B at a remote cabin with no one on site for
weeks, no remote power switch, and ~100 MB of swap. If it crashes, it stays down
until someone physically drives out. Treat every action on it as production
surgery with no undo.**

## Hard rules for the Pi — never break these

1. **Never run heavy or unbounded work on the Pi.** No analysis, correlation,
   bulk file reads, or anything that loads large or *growing* data into memory.
   The Pi runs only the lightweight logger / uploader / capture services.
   Everything else — decoding, correlation, backfills, one-off analysis — runs
   **off the Pi**: pull the data to the laptop and run it there.

2. **If you must run something ad-hoc on the Pi, bound it so it dies instead of
   killing the box.** Always wrap in `timeout`, and cap memory:
   ```
   systemd-run --scope -p MemoryMax=150M -p MemorySwapMax=0 -p RuntimeMaxSec=120 <cmd>
   ```
   Never launch a backgrounded, no-`timeout`, unbounded process on the Pi. Ever.

3. **Assume the data has GROWN.** A job that is safe with an hour of data is fatal
   with a month of it. Bound for the accumulated state, not today's. (This is the
   exact trap: the decoder was fine overnight with little data and OOM'd at midday
   with a day's worth. "It worked last time" is not safety.)

4. **The telemetry services must survive resource contention.** They carry
   `OOMScoreAdjust` so the kernel sacrifices a rogue job, not the mission. Never
   remove that protection.

5. **Every Pi change must be reversible from here.** If you cannot undo it over
   SSH from this laptop, do not do it. Know the rollback before you make the change.

6. **Default to looking, not touching.** Prefer read-only/observational commands
   on the Pi. A diagnostic that only reads is almost always safe; one that loads,
   writes, or spawns is not until proven bounded.

## Anti-drift — general discipline

- **Urgency never overrides safety.** "Seize the solar window / catch the moment"
  is precisely the rationalization that caused the outage. There is no deadline
  worth risking the only telemetry source at an unreachable site.
- **Small, reversible, verified.** Deploy one change, confirm it live, then move
  on. No sweeping multi-part changes to production in one shot.
- **Verify with evidence before asserting.** Check the actual state; don't claim.
- **Own mistakes with action, not words.** A fix deployed and a rule written beat
  an apology. Do the former.
- **When a thing is unrecoverable if it breaks, slow all the way down.** Re-read
  the command, ask "what's the worst case, and can I undo it remotely?", and only
  then run it.

## Useful recovery facts

- Data services are `enabled` with `Restart=always`, so a reboot restores
  telemetry on its own. A runaway *manual* process is finite: it will be
  OOM-killed and the Pi will recover without a power-cycle (just slowly).
- Heavy analysis tools default to bounded loads (e.g. `xanbus_decode.py` has
  `--hours` + `--max-frames`); run them off-Pi with the caps raised for full
  coverage.
- Access + SSH fallbacks: see memory `kwpi-ssh-paths`. Transport fallback (RS485
  ⇄ BLE): see `deploy/pi/README.md`.
