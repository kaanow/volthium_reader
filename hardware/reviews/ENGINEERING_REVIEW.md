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

**Domain-complete.** Cover *every* domain below, every pass. A deep dive
in one domain (e.g. electrical correctness) does not substitute for the
others — the most common miss is a thorough power review that never looks
at mechanical/RF/thermal/serviceability. Run the whole list even when one
area is consuming your attention.

**Spec-consistent.** Cross-check each CP doc against the **decisions log**
and the chosen *parts*. A spec that contradicts a later decision or the
actual part (e.g. a board-size or antenna-keepout line that a newer
decision superseded, or a keepout for a PCB-antenna variant when the BOM
lists the external-antenna part) is itself a finding — internal drift is
as real a defect as a wrong value.

> **Run the sweep mechanically, not opportunistically.** Do not rely on
> *noticing* stale references as you happen to read files — that misses
> whole un-audited doc areas (install guides, the system-vision doc, status
> files, firmware docs, original-intent netlist docs). After any decision
> that supersedes a part/value/enclosure/connector, build an alternation of
> the **superseded tokens** (old PNs, old enclosures, old net names, old
> dimensions) and `grep -rniE` it across the **whole repo** (quote the
> `--include='*.md'` globs so zsh doesn't expand them; exclude `/archive/`).
> Classify every hit: (a) intentional `was→now` history — leave; (b) a
> not-yet-rewritten generator/output that a later CP owns — note, don't fix;
> (c) a live contradiction in a current doc — fix now. Report a clean bill
> or the exhaustive remaining list. Opportunistic discovery is the failure
> mode; the mechanical sweep is the gate.

**Design-complete before handoff (do the work; don't outsource it).** A
reviewer is a second set of eyes on *completed* work, never a way to get the
work done. Before flipping to review, audit your own "request to the
reviewer": **every item must be a finished analysis with numbers that the
reviewer can re-derive and check against — not an open design question.**

> **The test:** read each ask aloud. If it's phrased as a question you don't
> know the answer to ("is a fixed variant orderable?", "does the stack fit?",
> "is the divider impedance OK?", "is either regulator marginal?"), it is a
> **design step you skipped**, not a review item — and that is a **FAIL**. Go
> do it: compute the number, resolve the part, dimension the stack, *then*
> ask the reviewer to independently re-derive and confirm. It is fine — good,
> even — to ask for an independent re-derivation of something high-stakes;
> the rule is only that *you must already have the answer on record* so there
> is something to check against. An asserted claim with no derivation ("60 V
> out-rates the clamp") is also incomplete: show the worst-case number and
> the margin. "Ask the reviewer" is not a substitute for "know the answer."

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
- **Physical / mechanical integration:** enclosure (type, material, IP
  rating) and how it interacts with the board — *plastic vs metal drives
  the antenna choice*; **RF environment** (antenna keepout matches the
  *actual* module variant; proximity to metal/batteries that detunes a PCB
  antenna); **thermal** dissipation paths for regulators/FETs; **mounting**
  (holes, standoffs, what it bolts to); **serviceability/access** — can
  you program/debug/replace-fuse/mate-connectors *without disassembly*
  where that's required; connector edge-placement, orientation, and
  cable-reach. **Board outline is an output of placement** — don't fix a
  size before parts are placed unless a real constraint demands it; "as
  small as comfortable, never artificially large."

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
4. **CP1 re-open** — a rigorous *electrical* pass (DR-3…DR-7) declared CP1
   "excellent" while the **mechanical** spec sat stale: the §2 envelope
   still listed the old board size, the wrong enclosure, and an antenna
   keepout for the wrong module variant. A deep dive in one domain masked
   a whole un-reviewed domain → the **domain-complete + spec-consistent**
   rules above.
5. **CP1 handoff** — the first "ready for review" packet asked the reviewer
   to *resolve* open questions (LM5166 fixed-vs-adjustable, regulator
   thermals, the display depth fit, the ADC source impedance) — i.e. it
   outsourced un-done design steps as if they were review items. Caught by
   the user: "those sound like design steps you skipped." → the
   **design-complete-before-handoff** rule above. The fix was to do every
   analysis first (clamp table, thermals, depth tally, fixed-PN resolution)
   so the reviewer re-derives against a real answer.

The pattern: every gate converts a hard, late-caught lesson into
front-loaded discipline so the *next* project gets it right from CP1.

**This applies at every CP, not just CP1.** Mechanical/physical
constraints set at CP1 must be *re-verified* downstream — placement (CP3/4)
honors the keepouts/access/thermal zones, routing (CP5) doesn't violate
them, and fab (CP6) confirms enclosure fit. A constraint is only "met"
when the latest artifact still satisfies it.
