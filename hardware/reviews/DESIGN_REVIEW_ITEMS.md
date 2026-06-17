# Design Review Items

Engineering concerns the build agents raise for a human call. Agents
decide routine matters themselves; an item lands here only when the
concern is substantive **and** the right answer depends on design intent
the agents can't recover from the files. Not a legacy/continuity log —
end-product correctness is the only bar. Each item is OPEN (awaiting a
call) or RESOLVED (with the decision recorded).

---

## DR-1 — Display TVS1 (SMAJ15A) orientation contradicts its part choice  [OPEN]

**Concern.** On the display 12 V input, TVS1 is wired **anode → V12_PROT
(+12 V rail), cathode → GND** (it uses the unidirectional `D` symbol with
value `SMAJ15A`). In that orientation a unidirectional TVS sits *forward*
across the rail: it gives **no positive-surge suppression** and only
conducts on reverse polarity (a crowbar that blows F1). But choosing a
15 V-stand-off TVS implies **surge-suppression** intent, which needs the
**opposite** orientation (cathode → rail, anode → GND). Part intent and
orientation disagree — one of them is wrong.

**Impact.** If surge suppression was intended, the +12 V input currently
has none. It is not a "won't power up" fault (the diode only conducts on
reverse/transient), which is why it passed ERC and visual review.

**Agent positions.**
- *Codex (reviewer):* passed it through CP1–CP6; never flagged.
- *Claude (designer):* preserved the orientation verbatim during the
  iter-15 layout reflow (would not silently alter a reviewed polarity),
  and raises the intent mismatch here.

**Why raised, not auto-fixed.** Flipping changes the protection behaviour;
which is correct depends on intent (surge suppression vs. reverse-polarity
crowbar) that isn't recorded anywhere. **Recommendation:** if the intent
is surge suppression — most likely, given the 15 V TVS — flip TVS1 to
cathode → rail. For contrast, the battery input *is* self-consistent:
series `SS24` Schottky for reverse polarity **plus** bidirectional
`SMAJ30CA` for surge.

**To resolve:** state the intent; I'll flip TVS1 (or close as-designed).
