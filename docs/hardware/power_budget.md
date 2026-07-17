# Power budget

The constraint: **average draw on the 24 V pack must be small compared
to the parasitic baseline of the cabin** — i.e. small relative to the
inverter's idle draw (~10–50 W). Goal is well under 1 W typical, with
the monitor self-disabling below 10 % SOC so it can't drain a sick
pack.

## Battery-side draw, per state

Conversion efficiency assumptions (per decisions.md D19):

- **U1 LM5166** (24 V → 3.3 V, *always-on*), IQ-SLEEP 9.7 µA typ /
  15 µA max (datasheet §6.5; the "~14 µA" previously quoted here was
  unsourced — corrected 2026-07-14 PDF audit); 70–85 % at 5–80 mA load. The microamp quiescent is the point — the always-on rail
  costs almost nothing at idle, which keeps the low-SOC trickle ~1 mW
  (the RV-3028-C7 RTC adds only 45 nA — D23).
- **U2 R-78HB12** (24 V → 12 V, *switched*, display feed), ~80 % over the
  relevant range. Behind the Q1 load switch, so it draws **zero** when
  the display is shed at < 10 % SOC.

### State 1 — Normal (> 25 % SOC, persistent BLE)

| Subsystem               | 3.3 V load        | 24 V draw (with conversion) | Note |
|-------------------------|-------------------|----------------------------|------|
| ESP32-S3 active (BLE)   | ~75 mA avg        | ~38 mA   ≈ 0.92 W           | BLE central holding 2 links + UART |
| RS-485 transceiver idle | ~1 mA             | ~0.5 mA                     | Driver disabled, receiver listening (idle bias is display-end only, DR-4b — no battery-side bias draw) |
| RV-3028-C7 RTC          | 45 nA             | negligible                  | (was DS3231 ~150 µA — DR-8) |
| **Battery-side subtotal**| —                | **~38 mA at 24 V ≈ 0.9 W**  | |
| Display-side via Cat5e  | (see below)       | +~5 mA at 24 V ≈ 0.12 W     |  |
| **Whole-system total (avg)** |              | **~43 mA at 24 V ≈ 1.0 W**  |  |
| WiFi log push (D25)     | ~150–250 mA for a ~2–6 s session, a few ×/hour | small added *average* | duty-cycled; logs buffered in flash between pushes (LM5166 500 mA feeds it) |

Per day: 1.1 W × 24 h = 26 Wh ≈ 1.1 Ah / day off the 24 V pack.
At 200 Ah usable per battery (400 Ah pack × ~85 % usable to 10 %),
that's ~340 days of monitoring on a fully charged pack with no other
load. Way under the budget.

### State 2 — Low SOC (15–25 %, BLE polling slows to 1/min)

| Subsystem            | Avg draw                         |
|----------------------|----------------------------------|
| ESP32-S3             | ~15 mA avg (mostly light-sleep, wakes for ~1 s once/min for BLE) |
| RS-485               | ~1 mA                            |
| RV-3028-C7 RTC       | 45 nA (negligible)               |
| Display side         | unchanged (~5 mA at 24 V)        |
| **Total**            | **~13 mA at 24 V ≈ 0.31 W**       |

### State 3 — Deep sleep (10–15 %, BLE off, ULP only)

| Subsystem            | Avg draw                         |
|----------------------|----------------------------------|
| ESP32-S3 ULP+RTC     | ~50 µA (RTC slow-clock + ULP wake every 10 min) |
| RV-3028-C7 RTC       | 45 nA (negligible)               |
| Q1/Q2 path off       | ~10 µA (pull-up leakage)         |
| Display side         | still receiving 12 V; ESP32 + e-paper light-sleep ≈ ~5 mA at 24 V conv. |
| **Total**            | **~5.4 mA at 24 V ≈ 0.13 W**      |

### State 4 — Hard cut (< 10 % SOC)

Q1 is OFF — the 12 V/display feed (U2) is shed, so the entire display
side is dark. The **ESP stays powered** on the always-on rail (U1) and
deep-sleeps, waking briefly to read the sense divider and re-engage Q1
when the pack recovers. No full power-down, no separate supervisor IC
(D19 / DR-4: a fully-unpowered MCU couldn't wake itself).

Terms are kept in their **native voltage domain** and only the buck-input
side is referred to the pack directly; 3.3 V loads are drawn from the
pack via U1's light-load efficiency. **Rows use the datasheet
*maximum* Iq where the datasheet publishes a spec max** (U1/U4/U6/U3);
**typical + explicit engineering margin** is used where no max is
published (ESP32-S3-WROOM Deep-sleep is 7-8 µA typ per Espressif Table 6-7
— citation corrected 2026-07-14, "§5.4" doesn't exist in the WROOM datasheet
with no listed max, so this table uses 10 µA typ + 5 µA margin = 15 µA;
RTC RV-3028-C7 at 45 nA typ / **60 nA max** per its own EC table @ 3 V,
25 °C — the earlier "≤200 nA per Micro Crystal AN" cited a document not
on file (corrected 2026-07-14 PDF audit); well under the µW floor). *(Reviewer iter-6 F03: prior rows mis-referred
3.3 V rail current to 24 V. Iter-10 F08: the iter-8 first cut quoted
transceiver shutdown Iq at typical (10 nA) instead of maximum (12 µA),
which triggered the ISL3175E → THVD1400DR reselection. Iter-12 F13
caught that my "max throughout" claim still mixed typ and max — this
"max where spec'd + explicit margin where not" wording is the corrected
convention used everywhere in the CP1 documents.)*

| Subsystem                                | Native draw (typ / **max** where spec'd) | Referred to pack (24 V) |
|------------------------------------------|------------------------------------------|-------------------------|
| U1 LM5166 input Iq (`IQ-SLEEP` no-load @ TJ = 25 °C) | 9.7 µA typ / **15 µA max** @ 24 V | **~0.36 mW** (max) |
| 24 V sense divider (R1+R2 = 1.3 MΩ)      | 24 V / 1.3 MΩ = 18.5 µA @ 24 V (fixed R) | **~0.44 mW** |
| UVLO divider (D28: R1≈5.16 MΩ/R2≈100 kΩ) | 4.56 µA @ 24 V (fixed R)                 | **~0.11 mW** |
| ESP32-S3-WROOM Deep-sleep (RTC + ULP off) | 7–8 µA **typ** per Espressif ES-datasheet **Table 6-7** (citation corrected 2026-07-14; no §5.4 exists); use **10 µA + ~5 µA engineering margin = 15 µA** @ 3.3 V (~50 µW) | ~0.10 mW (η ≈ 50 %) |
| U4 TPS3808G01 Iq (VDD_TPS = 3.3 V)       | 2.4 µA typ / **5 µA max** @ 3.3 V (~17 µW at max) | ~0.03 mW (η ≈ 50 %) |
| U6 TPS2116 mux Iq (Vout = 3.3 V, `IQ,VIN2`) | 1.35 µA typ / **4.5 µA max** over -40 to 105 °C (~15 µW at max) | ~0.03 mW (η ≈ 50 %) |
| U3 THVD1400DR RS-485 xcvr (D34, shutdown via DE=0+/RE=1) | 100 nA typ / **1 µA max** @ 3.3 V (~3.3 µW at max) | ~7 µW (η ≈ 50 %; below rounding) |
| RV-3028-C7 RTC (D23; VDD on V3V3)         | 45 nA typ / **60 nA max** @ 3 V, 25 °C (datasheet EC table; prior "≤200 nA per AN" cited an off-file document — corrected 2026-07-14); ~150 nW at typ | ~0.3 µW (η ≈ 50 %; below rounding) |
| Q1 (Si2309CDS) OFF **drain** leakage IDSS into the shed U2 branch (F65) | 1 µA **max @25 °C** / **10 µA max @TJ=55 °C** (68980 p.2, guaranteed) | ~0.02 mW @25 °C / **~0.24 mW @55 °C** |
| Q1 gate driver: Q2 (MMBT5551 BJT) OFF collector cutoff ICBO (F68) | **≤100 nA @ TA=100 °C** (guaranteed row) | ≤0.0024 mW (negligible, guaranteed to 100 °C) |
| Rest of display side (U2 shed)           | 0                                        | 0                       |
| **Total from pack** |  | **~1.13 mW @25 °C · ~1.35 mW @55 °C (both guaranteed rows)** |

The 3.3 V load-referred conversion uses a deliberately conservative
**η ≈ 50 %** light-load efficiency for the LM5166 at ~25 µA of output
load — LM5166's datasheet plots hit ~60–80 % at this current, so this
row is upper-bound. Even at η = 65 % the total is **~1.05 mW**; at
η = 80 % it drops to ~1.02 mW. Call it **~1.1 mW** headline honestly.

**Temperature dependence of the OFF-leakage terms — now a guaranteed
bound (F65/F68/F69).** Q1's OFF drain leakage rises with temperature but
Vishay guarantees the elevated-temp row (**10 µA max @55 °C**), so
~0.24 mW @55 °C is a *datasheet* bound, not an interpolation. The Q2
term used to be the interpolation problem (a 2N7002 with IDSS bounded
only at 25/125 °C); **F68 replaced Q2 with an MMBT5551 BJT whose ICBO is
guaranteed ≤100 nA at 100 °C**, so its contribution is ≤2.4 µW,
negligible and guaranteed well above any enclosure temperature. Result:
State-4 is **~1.13 mW @25 °C, ~1.35 mW @55 °C — both from guaranteed
datasheet rows** (no interpolation, no "60 °C estimate"). Absolute
battery impact is nil (even 2 mW on the ≈4.8 kWh stack is centuries);
the value matters as power-first discipline. Q1 OFF ≠ 0 (the earlier
"display side 0" row was wrong — F65).

**Honesty about typ vs max (reviewer iter-12 F13).** Prior versions of
this table claimed "max throughout" but several rows were actually
*typical* values (U1 was 14 µA, U4 2.4 µA, U6 1.3 µA, U3 shutdown "10 nA
typ / 12 µA max" carried as 10 nA). Rebuilt here with datasheet
*maxima* where the datasheet publishes them; ESP Deep-sleep is an
Espressif-typical figure with an explicit engineering margin added
(ESP32-S3-WROOM does not publish a spec max for Deep-sleep Iq — its
Table 6-7 lists 7–8 µA typical); RTC is 45 nA typ / 60 nA max per the
RV-3028-C7 datasheet EC table (negligible either way). *(2026-07-14 PDF
audit: this paragraph previously cited a "5.4 table" that doesn't exist
and previously pointed at an off-file Micro Crystal AN for a ≤200 nA
max — both citations replaced with figures read from the on-file
datasheets.)*

**Hardware floor (D28/DR-16), an even lower state below state 4.** If the
firmware ever fails to shed (hung-but-powered MCU), U4 asserts ESP **EN**
low below ~20 V pack: the ESP drops to its ~µA reset state (killing the
~38 mA hung drain) and the display auto-sheds (PWR_EN Hi-Z). Draw in
this floor state is only marginally lower than state 4 — U1 Iq + the
two dividers dominate (~0.91 mW), with only the ESP's ~15 µA (with
margin) going away (~0.10 mW saved) — total **~0.98 mW**. It holds
until the pack recovers past **~21.7–21.8 V** (release from the built-in
VHYS + external R_hys network; reviewer iter-5 F01 for polarity, iter-6
F04 for the release value).

At ~1 mW the pack would take **~10 years** to lose 1 % SOC from this
load alone — self-discharge and the cabin's own parasitics dominate by
orders of magnitude. (A literal full cut + hardware supervisor could
reach ~0.7 mW, but D19 judged the extra part not worth the marginal
saving.)

## Display-side draw

The display side gets 12 V over Cat5e. Looking at it from the display
end (before tracing back to the 24 V pack):

| Subsystem               | 3.3 V load (max where spec'd) | 12 V draw  | Note |
|-------------------------|--------------------------------|------------|------|
| ESP32-S3 active (RX only) | ~30 mA                       | ~10 mA     | Listening, refreshing e-paper occasionally |
| ESP32-S3 light-sleep    | ~2 mA                          | ~0.8 mA    | Most of the time |
| RS-485 receive-only (U2 THVD1400 RX, no load) | ~700 µA typ / **~900 µA max** | ~0.4 mA | Under F11 Deep-sleep wake: this term is continuous while the display is powered (State A+B). |
| **R3/R4 idle bias (DNP by default, iter-12 F12)** | **0 (not stuffed)** — populate only if bench shows EMI noise. If populated: **4.58 mA at 3.3 V ≈ 15 mW** whenever display is powered. | +1.6 mA if populated | THVD1400 §8.2.1.4 guarantees Full Fail-Safe RX without bias; power-first (D5) rule keeps it off the board by default. |
| E-paper during refresh  | ~25 mA × ~2 s every 30 s      | ~1.5 mA avg | Worst-case full refresh; partial refresh much less |
| E-paper static          | 0                              | 0          | The whole point of e-paper |
| **Display-side average**| —                              | **~3–5 mA at 12 V ≈ 50 mW** | With bias DNP; +18 mW if populated. |

At the **24 V pack** end, with 80 % conversion through U2 (R-78HB12),
that becomes ~63 mW.

## Wire loss

5 m of Cat5e at #24 AWG, 0.084 Ω/m per wire, round-trip on a single pair
is ~0.84 Ω. We use two pairs in parallel for +12 V (pair 2 + pair 3) and
one for GND (pair 4) — so:

- +12V resistance: 0.84 / 2 = 0.42 Ω
- GND resistance:  0.84 Ω
- Total loop:      1.26 Ω

At our peak transient (~50 mA during e-paper refresh): 63 mV drop. At
average (~5 mA): 6 mV drop. The R-78E3.3 needs ≥4.5 V input, so even
with a hypothetical 10 V cable arrival we're still in spec.

## Time-to-deplete (no charging) at each state

Assuming a fully charged 200 Ah pack with no other loads:

| State                              | Pack draw  | Days to 10 % cutoff |
|------------------------------------|------------|---------------------|
| Normal (state 1)                   | 1.1 W      | ~340 days           |
| Low (state 2)                      | 0.31 W     | ~1,200 days         |
| Deep sleep (state 3)               | 0.13 W     | ~2,800 days         |
| Hard cut (state 4)                 | ~1.13 mW @25 °C / ~1.35 mW @55 °C (guaranteed rows incl. Q1 IDSS + Q2 BJT ICBO — F65/F68) | decades (self-discharge dominates first) |

These are upper bounds — in reality the inverter idle is dozens of watts,
the cabin's fridge is ~5 A intermittent, etc. The monitor is rounding
error in the total cabin power budget.

## Sanity check: against the inverter

If the cabin is running the inverter to keep the kitchen outlet alive,
inverter idle is often 15–40 W. If we'd powered the display side from
that outlet instead of from the Cat5e DC feed, we'd spend ~20 W × 24 h =
**480 Wh/day** just to deliver 0.05 W to the e-paper. Twenty thousand
times the marginal cost of the DC-over-Cat5e approach. The DC path is the
right call.

That said: the inverter is likely on already for the fridge etc. anyway,
so the marginal cost of plugging the display end into AC is just the
wall-wart's load. Either approach works; the DC-over-Cat5e one survives
inverter-off conditions, which is the point.
