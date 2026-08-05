# CP3 placement iteration 11 reviewer report

Reviewed commit: `8a084a6`

The Windows rebuild precondition is green for all three generators, and the
structural build-directory rule independently closes finding 12. The mandatory
handoff still exits 1 because `handoff_check.py` explicitly supplies the old
`origin/main..HEAD` range, bypassing the checker's corrected default.

Two blockers remain:

1. Delete the stale range selection in `handoff_check.py` and invoke
   `reviewer_patch_check.py` without a range argument, so the one canonical
   epoch implementation is used. Add an integration poison that makes
   `origin/main` diverge and still requires handoff and standalone verdicts to
   agree.
2. Move the epoch constant out of routine reviewer-owned semaphore state.
   Pin the full policy-commit SHA in the checker (or another non-turn-control
   enforcement file) and, if the semaphore field remains for visibility,
   require exact equality with that constant. A semaphore-only reviewer commit
   must not be able to alter the scanned history.

Full command outputs and poisons are recorded in `rpa_windows_reverify.txt`.
Fresh top/bottom renders and eight crop regions show no placement regression.
