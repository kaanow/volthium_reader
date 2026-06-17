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

## DR-2 — Battery TVS1 (SMAJ30CA) clamp exceeds the buck's VIN rating  [OPEN]

**Concern.** Battery input topology is right — F1 fuse ✓, **series SS24
Schottky** for reverse polarity ✓, bidirectional `SMAJ30CA` TVS, bulk ✓.
But the voltage **coordination** is wrong: SMAJ30CA clamps at **~48 V**,
while the TPS62933 buck behind it is rated **~30 V (abs-max ~32 V)**. On
a surge the buck sees up to 48 V — well past its rating — *before* the
TVS clamps. The TVS does not actually protect the regulator.

Compounding it: a 24 V LiFePO4 bus reaches ~29 V at full charge, leaving
the 30 V buck only ~1 V steady-state margin. The part is under-rated for
a battery input that needs transient headroom.

**Why a single TVS can't fix it:** to not conduct at 29 V you need
`Vrwm ≥ ~29 V`, and any such TVS clamps well above 40 V — always above
the buck's 32 V. No standard TVS bridges the gap on a 30 V-max buck.

**Recommendation (your call — it's a regulator selection):** move the
3V3 buck to a **40–60 V-rated** part (e.g., a 60 V synchronous buck),
so the SMAJ30CA's 48 V clamp sits safely below its abs-max and the 29 V
bus has 2× margin. Then the existing fuse + SS24 + SMAJ30CA + bulk chain
becomes genuinely protective. Cheaper alternative if staying on a 30 V
buck: add series impedance + a lower-clamp TVS, but that is a worse,
lossier design.

**To resolve:** confirm the bus voltage (24 V nominal, ~29 V charged?)
and whether to re-spec the buck; I'll implement.
