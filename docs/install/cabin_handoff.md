# The Barge Inn battery monitor — short guide for cabin users

This page tells you how to read the monitor on your phone or laptop
and what to do about what it shows. No tech background needed.

## What it is

A live status board for the cabin's two big lithium batteries (the pair
under the floor). It shows you, in real time:

- **how full the batteries are** (SOC, "state of charge")
- **how long until they're full or empty** if today's pattern keeps going
- **whether the generator needs to run**, and if so, when and for how long

It runs on a laptop near the batteries and serves a webpage your phone
can open over the cabin Wi-Fi.

## Opening the dashboard

1. Make sure you're on the cabin Wi-Fi.
2. Open Safari / Chrome on your phone.
3. Go to **`http://192.168.1.76:8421/`** (or whatever the laptop's
   address shows on the *Volthium Monitor* launcher).
4. There's also a QR code on the laptop dashboard (bottom of the
   right column) — scan it with your phone Camera app to skip the
   typing.

## What you're looking at

The headline section, top of the page:

```
   ┌─────────────────────────────────┐
   │  [IDLE]  ← state (color chip)   │
   │                                  │
   │   72%          5h 20m            │  ← two big numbers
   │   state of   time to (95% / 10%) │
   │   charge                          │
   │   ▼ losing -2.2 A                │  ← trend ↓ losing, ↑ gaining, → steady
   │                                   │
   │   [████████░░░░░]                │  ← SOC bar
   │                                   │
   │   pack V  pack I  pack P         │  ← detail row
   └─────────────────────────────────┘
```

**The two things to actually look at** are the **big number on the left
(SOC)** and the **big number on the right (time remaining)**.

The trend line under SOC tells you which way the pack is heading
*right now*:

- **▲ gaining** (green) — charging from sun or generator
- **▼ losing** (yellow) — using more than the sun is making
- **→ steady** (dim) — roughly balanced

## What each state means

| Chip      | What it means                                                       |
|-----------|---------------------------------------------------------------------|
| **CHARGING** (green) | Net positive: sun or generator is filling the pack         |
| **DISCHARGING** (amber) | Net negative: cabin loads are pulling power        |
| **FULL** (bright green) | Pack at 95 %+ — generator not needed                   |
| **IDLE** (dim) | Less than 0.5 A flowing in either direction                     |

The "time remaining" updates a lot — that's normal. It's predicting
*at the current rate* how long until you hit a target (full or 10 %).
A fridge cycle starting up will temporarily lower it; the cycle ending
will raise it. Look at the trend over minutes, not seconds.

## The recommendation panel (below the live data)

Lower on the page you'll see a panel that says one of:

- **"no generator needed"** (green border) — projected to stay above
  25 % through tomorrow night. Relax.
- **"MORNING WATCH"** (amber border) — projected to dip below 50 %
  near tomorrow's sunrise. Not critical, but consider running the
  generator soon if today's forecast is gloomy.
- **"RUN GENERATOR · 1.4 h"** (amber/red border) — projected to drop
  below 25 %. The headline tells you how long to run the generator and
  when to start (usually a couple hours before sunrise).

A small chip says `low confidence` / `medium confidence` / `high
confidence`. While it says **low**, the projection is rough — the
system only has a couple days of data. Treat it as a hint, not gospel,
and be a bit conservative.

## When something looks wrong

| What you see                  | What to do                                          |
|-------------------------------|-----------------------------------------------------|
| All numbers say "—"           | The laptop is probably off. Restart **Volthium Monitor** on its desktop. |
| Time-remaining shows a giant number like "12000 min" | Current is near zero (very light load). Ignore; normal. |
| State is **DISCHARGING** all day | Sun isn't reaching the panels. Check for snow / debris. |
| Recommendation says **RUN GENERATOR** | Run the generator. The duration shown is the bare minimum. |

## What NOT to worry about

- **Brief BLE flap warnings in `data/pack.log`** — the system catches
  them automatically. They happen ~1×/hour as a normal thing.
- **SOC bouncing 1–2 %** — the BMS rounds to whole percent and a
  fridge cycle can briefly move it.
- **Battery A reading higher SOC than Battery B** — the two cells
  drift by a couple of percent. The lower one is what matters for
  the "empty" calculation.

## When NOT to trust it

While the **confidence chip says "low"** (the first 1–2 weeks):
- Tomorrow's forecast solar harvest is an educated guess.
- The dischargemodel doesn't yet have a week of patterns.
- Use the trend arrow + SOC % as your primary signals.

Each full day of data the system runs, the projection gets sharper.

## Bigger picture

This monitor is a stepping stone. A small wall-mounted version with
its own display is in progress — see `docs/production_design.md` and
`docs/hardware/` if you're curious. For now the laptop is doing the
job.

## Who to ask

Kaan made this. Issues and questions:
https://github.com/kaanow/volthium_reader/issues
