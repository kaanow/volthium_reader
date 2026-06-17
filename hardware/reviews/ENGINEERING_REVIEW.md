# Engineering Design Review

**ERC-clean + DRC-clean + readable ≠ correct.** This is the gate that
asks *"is this the right circuit, with the right parts, coordinated and
derated?"* — the question whose absence let DR-1 (TVS reversed) and DR-2
(48 V clamp into a 30 V buck) ride from CP1/CP2 all the way to CP6 with
every automated check green.

It runs at **two points, before placement/routing**:

- **CP1 (architecture):** voltage domains, topology and part-*class*
  choices, protection strategy, power/thermal budget. Catch the
  wrong-architecture errors while they are cheap.
- **CP2 (schematic):** every part's rating vs. its real operating
  conditions — concrete, per-part. Catch the wrong-value / wrong-part /
  mis-coordinated errors before they propagate into a layout.

The **designer** runs it and records findings before flipping the
semaphore; the **reviewer** re-derives it independently (a designer's
"PASS" is not evidence). Clear errors are fixed; judgment calls and
human-decision items go to `DESIGN_REVIEW_ITEMS.md`.

## Method — first principles, per net / block

1. **Threat & operating model.** What does this node *actually* see —
   max steady voltage (incl. charge/peak), surge/transient, reverse,
   inrush, ESD, temperature, fault currents?
2. **Clean-sheet topology.** Independently derive the textbook-correct
   circuit for this block. *Name it*, then measure the design against it
   — don't rationalise what's there.
3. **Part selection.** Does each part's class and rating suit its role?
   **Sanity-check availability + lifecycle the moment you pick a part** —
   a quick distributor stock + Active-vs-NRND/obsolete check, *not* only at
   BOM-lock. A chosen part that turns out unavailable or end-of-life
   cascades into footprint, symbol, and layout rework, so catch it while
   the choice is still cheap to change. BOM-lock remains the final
   verification; this is up-front insurance. Confirm the exact orderable
   variant matches the spec you assumed (e.g. fixed- vs adjustable-output,
   package, current grade) — the variant that's *in stock* may differ from
   the one you had in mind.
4. **Coordination (the rule most often missed).** Protective parts must
   *bracket* what they protect: TVS clamp < downstream abs-max; standoff
   > max operating; fuse rating < trace/connector limit; gate drive
   within FET Vgs.
5. **Derating.** Voltage headroom (caps behind a clamp rated > clamp;
   working ≤ ~½ rating where practical); current/power margin;
   temperature.
6. **Polarity / direction.** Diode and TVS orientation (and uni- vs
   bidirectional), electrolytic polarity, connector keying.
7. **Margin verdict.** Survives worst-case with headroom — not just
   typical.

## Per-domain checklist

- **Power input:** over-current (fuse/PTC); reverse polarity (series
  diode/ideal-diode, or crowbar); surge TVS (cathode→rail for a +rail,
  standoff > Vmax-charge, **clamp < downstream abs-max**); bulk caps
  rated > clamp; cabled inputs → ESD/EMI.
- **Regulation:** VIN rating > (bus max **and** surge clamp); Vout/Iout
  margin over worst-case load; all required support present and valued
  (L, input/output C, BOOT, FB divider, compensation); thermal at max
  load & VIN.
- **Comms:** termination, idle bias, fail-safe; ESD/TVS on cable-exposed
  lines; logic-level / voltage-domain match.
- **MCU:** decoupling per power pin; boot-strap / EN / reset states;
  brown-out; supply current budget vs. regulator capability.
- **Sensing:** divider ratio vs. ADC range; anti-alias / filter; input
  protection & clamp; source loading / burden.
- **Connectors:** pinout, keying, per-pin current & voltage rating,
  mating-cable assumptions.

## Lineage — why this gate exists

Three documented "looked done but wasn't" failure-modes, each answered
by adding the missing gate:

1. **iter-36** — a label-distance *script* passed while the PDF was
   unreadable → added the mandatory visual readability gate (D11/D16).
2. **iter-11** — the text-overlap audit passed while a power-port glyph
   sat on a resistor → added the comprehensive geometry audit.
3. **CP6** — ERC / DRC / readability all green while the input
   protection was mis-oriented (DR-1) and mis-coordinated (DR-2) →
   **this engineering-correctness gate.** These were CP1/CP2 decisions
   that nothing reviewed for *correctness*, only for legality and looks.

The pattern: every gate converts a hard, late-caught lesson into
front-loaded discipline so the *next* project gets it right from CP1.
