# CP1 review packet — Design baseline

**Status**: ready for review
**Opened**: 2026-05-23
**Reviewer**: TBD (separate agent or kaan)
**Branch**: `hw/cp1-design-baseline`
**Goal of this CP**: confirm the design is right *before* we draw it in
KiCad. Catch anything that's wrong, missing, or open-ended now — fixing
it later costs much more.

## 1. What this CP delivers

A complete, self-contained design specification for both boards, with
every part, every net, every design rule, every open question
explicitly called out. From here, CP2 (schematic capture) is supposed
to be **mechanical translation** — no new design decisions.

Files added in this CP:
- [`../layout/decisions.md`](../layout/decisions.md) — every committed
  decision and rationale; the source of truth for "what did we agree to"
- [`../layout/cp1_battery_side.md`](../layout/cp1_battery_side.md) —
  battery-side board baseline
- [`../layout/cp1_display_side.md`](../layout/cp1_display_side.md) —
  display-side board baseline
- [`../layout/cp1_bom.md`](../layout/cp1_bom.md) — consolidated BOM with
  vendor SKUs and Δ vs prior pass

Plus the supporting scaffolding from the previous commit:
[`hardware/layout/README.md`](../layout/README.md) (process index),
[`hardware/reviews/README.md`](README.md) (this folder's README),
and KiCad project subdirectories.

## 2. What changed since the original `docs/hardware/` spec

The prior pass produced engineering-spec markdown plus SKiDL Python
that targets KiCad 8. CP1 takes that as input and makes the **set of
small refinements** below before committing to KiCad capture. Each one
is justified in the relevant doc with a Δ annotation.

### Material design changes

1. **Display-side enclosure** moved from single-gang plate → US
   double-gang plastic old-work box with 3D-printed faceplate.
   ([cp1_display_side.md §2](../layout/cp1_display_side.md#2-mechanical-envelope))
2. **24 V sense divider** raised from 100 kΩ/11 kΩ to 1 MΩ/110 kΩ
   (always-on idle current dropped 220 µA → 22 µA).
3. **Q1 gate pull-up** raised from 10 kΩ to 100 kΩ (idle current dropped
   2.4 mA → 240 µA).
4. **Button pull-ups** (3× on display, 1× on battery) raised from 10 kΩ
   to 1 MΩ (idle Iq nearly zero per button).
5. **Power input on battery side** changed from external ring lugs +
   ATO fuse to on-board Phoenix MSTB terminal block + 5×20 mm cartridge
   fuse. Cleaner enclosure, still field-serviceable.
6. **Display-side button function** moved from hardcoded (refresh /
   next / release-BLE) to software-defined, with on-screen labels
   adjacent to each button.
7. **Debug LEDs (LED1, R_led)** removed on both boards. Power-first.
8. **TVS numbering** reconciled across schematic doc + SKiDL +
   block diagram (they disagreed).
9. **24 V TVS** added (TVS1 SMAJ30CA on V24_FUSED). Wasn't in the
   original schematic doc; SKiDL had it under a different number.
10. **Battery-side enclosure** changed from Hammond 1556B2GY to 1591ATBU
    (smaller, easier to stock, fits the 60×40 mm board).
11. **Dev/debug headers** added on both boards (UART debug, USB-OTG
    breakout, RS-485 term-lift jumper).

### Soft changes (clarifications, not new decisions)

- E-paper choice locked in: 4.2" tri-color BWR with mixed-mode refresh
  (B&W partial ~500–700 ms for button UI, color full ~7 s for
  scheduled ticks). See [decisions.md D6](../layout/decisions.md#d6).
- Refresh policy: button presses get partial refresh; color refresh
  happens on the next scheduled background tick (30–60 s) or on a
  state-change alert.
- Source of truth = KiCad 10 native files (.kicad_pro / .kicad_sch /
  .kicad_pcb). Existing SKiDL preserved as design-intent reference but
  not regenerated from.
- Fab = JLCPCB, 2-layer FR-4, qty 5 of each board (their minimum),
  bare PCB (no PCBA — economics don't make sense at qty 1).
- Assembly = hand-solder.

## 3. What to look at first

If you have 15 minutes:
1. [decisions.md](../layout/decisions.md) — 10-minute read; gives the
   committed shape of every decision.
2. [cp1_battery_side.md §5 (net list)](../layout/cp1_battery_side.md#5-net-list)
   — sanity check the net topology.
3. [cp1_battery_side.md §13 (open decisions)](../layout/cp1_battery_side.md#13-open-decisions-for-reviewer)
   and [cp1_display_side.md §12](../layout/cp1_display_side.md#12-open-decisions-for-reviewer)
   — the things I want your input on before we proceed.

If you have an hour: read all three CP1 docs end-to-end. Pay particular
attention to:
- Pin assignments — anything I assigned that should be a different GPIO
  for hidden ESP32-S3 reasons (boot straps, ADC2 conflict with WiFi,
  etc.)
- Power-state arithmetic — does the budget per state hold up under
  realistic loads?
- BOM SKU availability — JLC stock, DigiKey availability for the parts
  marked "unchanged" (some may have ROHS/EOL flags since the original
  doc was written)

## 4. Open decisions awaiting input

Repeated here for convenience. Defaults are what I'll use if the
reviewer doesn't override.

### Battery-side

| ID | Question | Default |
|----|----------|---------|
| D-OPEN-1 | ESP32-S3-WROOM-1-N16R8 vs -N8 (no PSRAM)? | N16R8 |
| D-OPEN-2 | SN65HVD3082E vs lower-Iq alternative (ISL3175E)? | SN65HVD3082E |
| D-OPEN-3 | Internal ESP32 ADC vs external supervisor IC (TPS3839) for ULP voltage monitoring? | Internal ADC |
| D-OPEN-5 | Hard-cut topology — original P-FET-in-24V vs EN-pin-shutdown? | Original P-FET |
| D-OPEN-6 | Q1 gate pull-up value — 10 kΩ vs 100 kΩ vs 1 MΩ? | 100 kΩ |
| D-OPEN-7 | Should the 12 V Cat5e rail die in deep-sleep/hard-cut? | No |
| D-OPEN-13 | Panel-mount switch BTN1 sealing — IP67 cap or open? | Open (in-box, no water concern) |

### Display-side

| ID | Question | Default |
|----|----------|---------|
| D-OPEN-1 | Same N16R8 vs N8 question | N16R8 |
| D-OPEN-8 | Populate R3/R4 idle-bias on display side? | No (footprints provided) |
| D-OPEN-9 | RS-485 receiver power-gate (N-FET on U2 VCC)? | No (defer to v2) |
| D-OPEN-10 | Button hardware-debounce RC values? | 100 ms (1 MΩ + 100 nF) |
| D-OPEN-11 | Panel mount location — PCB, bracket, or faceplate? | On bracket |
| D-OPEN-12 | Faceplate dimensions — 115 × 117 mm or other? | 115 × 117 |
| D-OPEN-14 | JLCPCB PCBA option — defer to v2? | Defer |

## 5. Known unknowns / things I cannot verify without you

- **JLCPCB stock** of certain parts (Recom R-78 modules, DS3231SN#) at
  order time. CP1 lists DigiKey + Mouser SKUs; JLC order will be
  bare-PCB only so JLC-specific stock isn't blocking, but I flagged it.
- **Waveshare 4.2" e-Paper (B) v2 panel FFC pinout** — the SKiDL had a
  placeholder mapping. CP1 commits to verifying against the panel
  datasheet at CP2 before any KiCad capture; flagging here so the
  reviewer knows there's an unresolved detail downstream.
- **3D-printed bracket and faceplate dimensions** — user-designed. CP1
  commits to providing a PCB STEP file at CP5; the design is the user's
  responsibility.
- **Cat5e in-wall run condition** — assumed shielded per
  [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md); unshielded
  also works (per that doc), but the shield-bonding scheme in CP1
  assumes shielded.

## 6. Success criteria

This checkpoint passes when:

- [ ] Every decision in [decisions.md](../layout/decisions.md) is either
      approved or explicitly redirected
- [ ] Every D-OPEN-N item is resolved (use the default, override it, or
      acknowledge it's not yet decided and flag for resolution at a
      later CP)
- [ ] BOM has no flagged stock-unavailable items
- [ ] No new design questions surface from a careful read of the three
      CP1 docs
- [ ] Reviewer signs off on the section "What changed since the original
      `docs/hardware/` spec" as a complete + correct enumeration of
      deltas

If any of those fail, fix in this CP before opening CP2.

## 7. What this CP does NOT settle

- The actual KiCad schematic capture (CP2 work)
- Net-by-net verification in the symbol library (CP2)
- Footprint selection / placement (CP3)
- Routing decisions (CP4)
- Fab-rendering details (CP5)

## 8. Reviewer findings (append-only)

*(reviewer: append findings below, with timestamps. Each finding either
gets a `RESOLVED` entry from me, or escalates to a decision change in
decisions.md.)*

---
