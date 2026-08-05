# CP3 placement iteration 9 reviewer report

Reviewed commit: `7edf009`

The Windows-specific F10 implementation itself passes: two consecutive full
handoff rebuild sets completed with all three generators at `rc=0`, with no
recurrence of the transient `EINVAL` failure. The exact handoff still exits 1
because its new RPA checker retroactively classifies four CP2 evidence commits
and one pre-policy Windows host fix as unauthorized reviewer patches.

Two checker defects remain blocking:

1. The default `origin/main..HEAD` enforcement range has no policy baseline or
   complete legacy-acceptance registry, while acceptance lookup is limited to
   the active packet. This makes the mandatory handoff red on clean current
   work. Use a committed RPA enforcement base (the policy-introduction commit
   is `3e4c097`) or a complete legacy registry; do not classify reviewer-owned
   `visual_inspections/**` evidence scripts as product-code patches.
2. The zero-delta deny list does not cover generated PNG, PDF, SVG, report, or
   JSON outputs. Deny the known generated build directories as an inventory,
   or derive the inventory from the handoff generator outputs, then poison-test
   all five missed artifact classes.

Four source-PDF citations were independently rechecked and fresh top/bottom
KiCad renders plus eight crop regions were inspected. No placement or source
assumption regression was found. Full command-level evidence is in
`windows_handoff_and_rpa.txt`.
