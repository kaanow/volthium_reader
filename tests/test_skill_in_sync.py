"""The xanbus skill must not drift from its versioned copy.

The skill at `volthium_sw/.claude/skills/xanbus/SKILL.md` is what every future
session is told to consult first, and it lives OUTSIDE this repo — unversioned,
no history, no backup. On 2026-08-10 it was found to still document the naive
latch test (`delta < 2.5`), which is the exact bug that fired a false positive
at 21:24 with delta -15.7 V and later bounced the MPPT after sunset. Anyone
following the skill would have rebuilt the defect.

So the repo keeps a copy. But an unguarded mirror is just drift with extra
steps — this whole file exists because a document went stale — so this test
fails the moment the two diverge, in either direction.

It SKIPS when the live skill is absent (a clone elsewhere, or CI), because the
point is to catch divergence on the machine where both exist, not to make the
suite depend on a path outside the repo.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_COPY = Path(__file__).resolve().parents[1] / "docs/skills/xanbus-SKILL.md"
LIVE = (Path(__file__).resolve().parents[2]
        / ".claude/skills/xanbus/SKILL.md")


class SkillSyncTests(unittest.TestCase):

    def test_repo_copy_exists(self):
        self.assertTrue(REPO_COPY.is_file(),
                        f"versioned copy missing: {REPO_COPY}")

    def test_live_skill_matches_the_versioned_copy(self):
        if not LIVE.is_file():
            self.skipTest(f"no live skill at {LIVE} — nothing to compare")
        live, repo = LIVE.read_text(), REPO_COPY.read_text()
        if live == repo:
            return
        import difflib
        diff = "\n".join(list(difflib.unified_diff(
            repo.splitlines(), live.splitlines(),
            "docs/skills/xanbus-SKILL.md", "live skill", lineterm=""))[:40])
        self.fail("the xanbus skill and its versioned copy have diverged.\n"
                  "Copy whichever is correct over the other, deliberately —\n"
                  "do not assume the live one wins.\n\n" + diff)

    def test_the_corrected_detector_band_is_documented(self):
        """The specific regression this guards. A skill that still says
        `delta < 2.5` teaches the reader to rebuild a shipped bug."""
        text = REPO_COPY.read_text()
        self.assertIn("0.3 V ≤ pv_v − out_v ≤ 4.0 V", text)
        self.assertNotIn("**Detect:** `pv_v − out_v < 2.5 V`", text)


if __name__ == "__main__":
    unittest.main()
