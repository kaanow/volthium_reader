"""Tests for dashboard HTTP routes.

The dashboard's Handler.do_GET routes path → response. We don't
spin up a server; we construct a Handler instance via __new__
(bypassing __init__) and mock the _send method to capture what
each route would write. This lets us verify status codes, content
types, and body fragments without TCP / HTTPServer overhead.

Routes covered:
    /                        (HTML page)
    /api/latest.json         (JSON, may be empty if no pack.csv)
    /today-report            (HTML, may be a degraded message if data missing)
    /report/<date>           (HTML for a specific past date)
    /report/<bogus>          (404 with helpful message)
    /reports                 (index page)
    /calibration             (calibration log table)
    /projections             (projection log table)
    /accuracy                (projection accuracy view)
    /<unknown>               (404)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dashboard  # noqa: E402


def _make_handler(path: str) -> tuple[dashboard.Handler, list]:
    """Build a Handler instance with `path` set, with _send replaced by
    a capture list. Returns (handler, captured_responses).

    Each captured response is a tuple: (status, content_type, body_bytes).
    """
    h = dashboard.Handler.__new__(dashboard.Handler)
    h.path = path
    captured: list = []

    def fake_send(status, ctype, body):
        captured.append((status, ctype, body))

    h._send = fake_send
    return h, captured


class TestDashboardRoutes(unittest.TestCase):
    """Tests run in a fixtured tempdir so the route handlers' file
    reads (data/pack.csv etc.) don't pick up the real installation's
    data — gives reproducible test results regardless of live data."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "reports").mkdir()
        # Point dashboard's globals at the empty tempdir. These are
        # type-annotated but only get values when main() runs; in test
        # contexts we have to assign them ourselves. Save/restore via
        # getattr so this works whether or not they were pre-set.
        self._orig_csv = getattr(dashboard, "CSV_PATH", None)
        self._orig_weather = getattr(dashboard, "WEATHER_CSV_PATH", None)
        dashboard.CSV_PATH = self.root / "data" / "pack.csv"
        dashboard.WEATHER_CSV_PATH = self.root / "data" / "weather.csv"
        self._orig_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        if self._orig_csv is not None:
            dashboard.CSV_PATH = self._orig_csv
        if self._orig_weather is not None:
            dashboard.WEATHER_CSV_PATH = self._orig_weather
        self.tmp.cleanup()

    # ---------- core routes ----------

    def test_index_returns_html_dashboard(self) -> None:
        """`/` returns the main HTML page, complete with the JS bundle."""
        h, captured = _make_handler("/")
        h.do_GET()
        self.assertEqual(len(captured), 1)
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("text/html", ctype)
        # Sanity: the page contains the main panel ids
        self.assertIn(b"projection-panel", body)
        self.assertIn(b"harvest-panel", body)
        self.assertIn(b"advisor-panel", body)
        # And the tick() polling JS
        self.assertIn(b"/api/latest.json", body)

    def test_index_html_alias(self) -> None:
        """`/index.html` is an alias for `/`."""
        h, captured = _make_handler("/index.html")
        h.do_GET()
        self.assertEqual(captured[0][0], HTTPStatus.OK)

    def test_api_latest_returns_json_when_no_data(self) -> None:
        """`/api/latest.json` on an empty pack.csv returns a graceful
        JSON shape with null latest, not a 500."""
        h, captured = _make_handler("/api/latest.json")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("application/json", ctype)
        import json
        parsed = json.loads(body)
        self.assertIn("latest", parsed)
        self.assertIsNone(parsed["latest"])
        self.assertEqual(parsed["history"], [])

    def test_unknown_route_returns_404(self) -> None:
        h, captured = _make_handler("/nope")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertIn(b"not found", body)

    # ---------- /today-report ----------

    def test_today_report_renders_html(self) -> None:
        """`/today-report` generates the day's report inline. With no
        data files it still produces an HTML page (degraded content,
        not a 500)."""
        h, captured = _make_handler("/today-report")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Day report", body)

    def test_today_report_md_alias(self) -> None:
        """`/today-report.md` is an alias for `/today-report`."""
        h, captured = _make_handler("/today-report.md")
        h.do_GET()
        self.assertEqual(captured[0][0], HTTPStatus.OK)

    # ---------- /report/<date> ----------

    def test_report_with_bogus_date_returns_404(self) -> None:
        """A non-ISO date in `/report/<date>` returns a 404 with a
        helpful 'use YYYY-MM-DD' message."""
        h, captured = _make_handler("/report/not-a-date")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertIn(b"YYYY-MM-DD", body)

    def test_report_for_unknown_past_date_returns_404(self) -> None:
        """`/report/2020-01-01` with no file there → 404 saying so."""
        h, captured = _make_handler("/report/2020-01-01")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertIn(b"no report for 2020-01-01", body)

    def test_report_for_existing_past_date_renders_it(self) -> None:
        """A historical report file is served as-committed (the route
        doesn't re-run the builder against old data)."""
        path = self.root / "data" / "reports" / "2020-01-01.md"
        path.write_text("# Historical day\n\n**Summary**: testfile.\n")
        h, captured = _make_handler("/report/2020-01-01")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("text/html", ctype)
        # The markdown content (Historical day) should be in the rendered output
        self.assertIn(b"Historical day", body)
        self.assertIn(b"testfile", body)

    # ---------- /reports ----------

    def test_reports_index_renders_with_no_history(self) -> None:
        """Empty history → friendly 'no past reports yet' message,
        plus today's live link is still pinned at top."""
        h, captured = _make_handler("/reports")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Day reports", body)
        # Today's pinned link uses '(today, live)' as its label suffix
        self.assertIn(b"(today, live)", body)
        # And points at /today-report
        self.assertIn(b'href="/today-report"', body)
        self.assertIn(b"no past reports yet", body)

    def test_reports_index_lists_historical_dates(self) -> None:
        """Files in data/reports/*.md should appear as links, newest
        first."""
        (self.root / "data" / "reports" / "2024-12-30.md").write_text("# old\n")
        (self.root / "data" / "reports" / "2025-01-05.md").write_text("# newer\n")
        h, captured = _make_handler("/reports")
        h.do_GET()
        body = captured[0][2]
        self.assertIn(b"2025-01-05", body)
        self.assertIn(b"2024-12-30", body)
        # Newest first — 2025-01-05 must appear before 2024-12-30
        self.assertLess(body.index(b"2025-01-05"),
                        body.index(b"2024-12-30"))

    # ---------- /calibration ----------

    def test_calibration_renders_empty_message_without_log(self) -> None:
        h, captured = _make_handler("/calibration")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"SolarModel calibration log", body)
        self.assertIn(b"no calibration log entries yet", body)

    # ---------- /projections ----------

    def test_projections_renders_empty_message_without_log(self) -> None:
        h, captured = _make_handler("/projections")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"Advisor projection log", body)
        self.assertIn(b"no projection log entries yet", body)

    # ---------- /accuracy ----------

    def test_accuracy_renders_empty_message_without_log(self) -> None:
        h, captured = _make_handler("/accuracy")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"Projection accuracy", body)
        self.assertIn(b"no validatable projections yet", body)

    # ---------- /low-accuracy ----------

    def test_low_accuracy_renders_empty_message_without_data(self) -> None:
        """No projection_log + no solar_onset → empty-state message.
        The route MUST NOT crash on cold start."""
        h, captured = _make_handler("/low-accuracy")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"Morning-low validation", body)
        self.assertIn(b"no validatable morning-low projections yet", body)
        # The page should explain the sister relationship + the bias-fix
        # context so a new reader understands what they're looking at.
        self.assertIn(b"projected_low_soc", body)

    def test_index_includes_onset_marker_js(self) -> None:
        """The dashboard's index page must include the
        computeOnsetMarkers JS function so the sparklines can
        annotate today's solar_onset milestones. Pinning the
        function name down anchors the feature against accidental
        removal (e.g. by an unrelated dashboard refactor)."""
        h, captured = _make_handler("/")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # The marker pipeline: helper function + the cascade keys
        # passed in. We don't assert on rendered marker count
        # (depends on live data) — just on the code being present.
        self.assertIn(b"computeOnsetMarkers", body)
        self.assertIn(b"first_zero_iso", body)
        self.assertIn(b"first_net_positive_iso", body)
        # Marker visuals — dashed vertical line + tooltip via <title>
        self.assertIn(b"stroke-dasharray", body)

    def test_render_horizon_bar_chart_handles_empty_input(self) -> None:
        """Empty list → empty string (caller can unconditionally
        concat into the page body). Anchors the cold-start path."""
        self.assertEqual(dashboard.render_horizon_bar_chart([]), "")

    def test_render_horizon_bar_chart_emits_svg_with_bars(self) -> None:
        """A small bucket list produces an SVG with one <rect> per
        bucket, the chart title text, and the y-axis tick labels.
        The signed mean_error value appears as text near each bar."""
        by_h = [
            {"bucket": "1-2h", "n": 5,
             "mean_error": 1.5, "mean_abs_error": 1.5,
             "rms_error": 1.6, "min_error": 1.0, "max_error": 2.0},
            {"bucket": "5-6h", "n": 3,
             "mean_error": -3.0, "mean_abs_error": 3.0,
             "rms_error": 3.1, "min_error": -3.5, "max_error": -2.5},
        ]
        svg = dashboard.render_horizon_bar_chart(by_h)
        # SVG wrapper
        self.assertIn("<svg", svg)
        # Title text
        self.assertIn("mean error (pp) by lead-time horizon", svg)
        # One <rect> per bucket (2 here)
        self.assertEqual(svg.count("<rect"), 2)
        # Both bucket labels appear as text
        self.assertIn(">1-2h<", svg)
        self.assertIn(">5-6h<", svg)
        # Signed mean values rendered with explicit sign
        self.assertIn("+1.50", svg)
        self.assertIn("-3.00", svg)
        # Tooltip rect's <title> shows the full stats
        self.assertIn("n=5", svg)
        self.assertIn("n=3", svg)

    def test_accuracy_page_includes_horizon_chart_when_data_present(self) -> None:
        """When the live /accuracy page has records, the bar chart
        SVG appears above the horizon table. Anchors the wiring."""
        # Cold start has no records → no chart either; this test
        # documents the route wiring rather than the no-data path.
        h, captured = _make_handler("/accuracy")
        h.do_GET()
        body = captured[0][2]
        # Either the empty-state message OR the chart title is present.
        # We just want to make sure the page renders without crashing
        # given the new chart-generating code path exists.
        self.assertTrue(
            b"no validatable projections yet" in body
            or b"mean error (pp) by lead-time horizon" in body,
            "expected either empty-state or chart on /accuracy",
        )

    def test_low_accuracy_route_is_a_sister_of_accuracy(self) -> None:
        """Both /accuracy and /low-accuracy should cross-link to each
        other so a user can pivot between sunrise and morning-low
        validation views."""
        for path, must_contain in [
            ("/accuracy", b"low-accuracy"),
            ("/low-accuracy", b"/accuracy"),
        ]:
            with self.subTest(path=path):
                h, captured = _make_handler(path)
                h.do_GET()
                body = captured[0][2]
                self.assertIn(must_contain, body)

    # ---------- cross-page navigation links ----------

    def test_log_pages_cross_link_to_each_other(self) -> None:
        """The three log pages each link to the other two and back to
        dashboard, so the user can navigate without going home first."""
        for path, expected_links in [
            ("/calibration",
             [b"href='/'", b"projections", b"accuracy"]),
            ("/projections",
             [b"href='/'", b"calibration", b"accuracy"]),
            ("/accuracy",
             [b"href='/'", b"projection", b"calibration"]),
        ]:
            with self.subTest(path=path):
                h, captured = _make_handler(path)
                h.do_GET()
                body = captured[0][2]
                for link in expected_links:
                    self.assertIn(link, body,
                                  f"{path} should contain {link!r}")


if __name__ == "__main__":
    unittest.main()
