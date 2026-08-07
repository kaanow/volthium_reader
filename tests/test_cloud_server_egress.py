"""Egress-hygiene guards for the cloud FastAPI server.

The Railway deployment once ran ~9 GB/day of egress — the dashboard was
re-downloading a 538 KB readings payload every 5 s, uncompressed. The fix
was app-wide gzip plus incremental (`?since=`) fetching. These tests lock
in the two things that must not silently regress:

  1. GZipMiddleware stays installed (compresses ALL responses ~13x —
     dashboard, history page, every /api route, static files).
  2. /api/readings still advertises the `since` param that lets the
     dashboard and status_check fetch only new rows instead of the whole
     history.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The server's deps are not installed everywhere the unit suite runs (the repo
# is developed against the system python, the server against Railway's image).
# SKIP in that case rather than ERROR: a suite that can never go green teaches
# people to ignore it, and these two guards then protect nothing.
try:
    import fastapi  # noqa: F401
    HAVE_FASTAPI = True
except ImportError:                                      # pragma: no cover
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed in this interpreter")
class CloudServerEgressGuards(unittest.TestCase):
    def test_gzip_middleware_enabled(self):
        from fastapi.middleware.gzip import GZipMiddleware

        from cloud.server.main import app

        self.assertTrue(
            any(m.cls is GZipMiddleware for m in app.user_middleware),
            "GZipMiddleware must stay enabled — it is the app-wide fix that "
            "keeps API/dashboard/history egress ~13x smaller.",
        )

    def test_readings_supports_since_param(self):
        # The incremental-fetch contract: /api/readings must accept `since`
        # so clients fetch only new rows. Assert the route's signature keeps it.
        import inspect

        from cloud.server.main import api_readings

        params = inspect.signature(api_readings).parameters
        self.assertIn(
            "since", params,
            "/api/readings must keep the `since` param — the dashboard's "
            "incremental poll and status_check's windowed fetch depend on it.",
        )


if __name__ == "__main__":
    unittest.main()
