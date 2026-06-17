# Design Review Items

Engineering concerns the build agents raise for a human call. Agents
decide routine matters themselves; an item lands here only when the
concern is substantive **and** the right answer depends on design intent
the agents can't recover from the files. Not a legacy/continuity log —
end-product correctness is the only bar. Each item is OPEN (awaiting a
call) or RESOLVED (with the decision recorded).

---

## Best-practice baseline (clean sheet)

For a DC input arriving from off-board, connector inward:
1. **Overcurrent** — fuse / PTC polyfuse.
2. **Reverse polarity** — series element (Schottky = simple; ideal-diode
   P-FET = low loss).
3. **Surge/transient** — unidirectional TVS, **cathode → rail**, sized so
   `Vrwm ≥ max operating V` (with margin) **and** `Vclamp ≤ downstream
   abs-max VIN`. The clamp must land *below* what it protects.
4. **Bulk capacitance.**
5. Cabled inputs: optional LC / common-mode filtering for EMI/ESD.

The decisive, often-missed rule is 3: a TVS only protects if its clamp
voltage is below the abs-max of the part behind it.

## DR-1 — Display TVS1 (SMAJ15A) was reversed  [RESOLVED 2026-06-17]

Display 12 V input was: F1 polyfuse ✓, bulk C1 ✓, **TVS1 anode→rail /
cathode→GND** ✗ — a unidirectional TVS forward across the rail gives no
positive-surge clamp (only a reverse-polarity crowbar). The part is
correctly *sized* for surge (Vrwm 15 V > 12 V; Vclamp ~24 V < R-78E3.3
VIN max ~32 V), which proves surge intent — so the orientation, not the
part, was the error. Codex passed it CP1–CP6; Claude raised it.

**Resolution (agent call):** the clean-sheet analysis removed the
ambiguity, so flipped TVS1 to **cathode→rail** (angle 270). Now
reverse-biased in normal operation, clamps positive transients. ERC 0/0,
audit PASS. Residual gap vs. ideal: no dedicated series reverse-polarity
device — judged acceptable for a fixed, keyed inter-board CAT5e feed
(a series Schottky is an available enhancement if field miswiring is a
real risk; say so and I'll add it).

## DR-2 — Battery TVS clamp exceeded the buck's VIN rating  [RESOLVED 2026-06-17]

**Was.** Battery input topology was right (F1 fuse, series SS24 Schottky
reverse-polarity, TVS, bulk) but mis-**coordinated**: `SMAJ30CA` clamps
~48 V while the TPS62933 buck was rated ~30 V (abs-max ~32 V) — a surge
would destroy the buck *before* the TVS protected it. A single TVS can't
fix it (to clear a ~29 V full-charge bus it needs Vrwm ≥ 29 V, which
clamps > 40 V — always above 32 V).

**Resolution (agent call, per "make the excellent choice").** Raised the
regulator above the clamp instead of trying to lower the clamp:
- **3V3 buck → Recom R-78HB3.3-0.5 module (9–72 V VIN).** 72 V rating
  tolerates the ~53 V clamp with margin. Drops the inductor + bootstrap
  cap, and makes all three rails (battery 3V3, battery 12 V U2, display
  3V3) the same R-78 family.
- **TVS1 → SMAJ33CA.** 33 V stand-off gives clean margin over the ~29 V
  full-charge bus (30 V was ~1 V — could leak/clamp in normal use).
- **Input bulk caps on V24_SW (C1, C3) → 100 V.** They sit behind the
  TVS and can see its ~53 V clamp; the old 25 V / 35 V parts were a
  latent short-on-surge.

Net result: fuse → SS24 → SMAJ33CA → 100 V bulk → 72 V module is now a
genuinely protective, well-coordinated chain. Verified U1 VIN→V24_SW,
GND→GND, VOUT→V3V3_SW; ERC 0/0, audit gate PASS.

**Trade accepted:** R-78HB is 0.5 A (vs the old 3 A discrete). The
battery 3V3 load (ESP32-S3 + RTC + RS-485) peaks ≲0.5 A and is buffered
by bulk caps — the display side already runs the same ESP32-S3 on a
0.5 A R-78. If the battery node ever needs >0.5 A, revisit with a 60 V
discrete buck.
