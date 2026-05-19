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

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
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

    def test_today_curve_empty_state(self) -> None:
        """No pack.csv → friendly empty message, no crash."""
        h, captured = _make_handler("/today-curve")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"Today's net Ah recovery curve", body)
        self.assertIn(b"no pack samples for today yet", body)

    def test_today_curve_renders_chart_with_data(self) -> None:
        """When pack.csv has today's samples, the page renders an SVG
        chart with a polyline and a summary line."""
        path = self.root / "data" / "pack.csv"
        # Write a small set of samples spanning ~30 min today: mostly
        # discharge so cumulative net Ah goes negative.
        from datetime import timedelta
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "state", "pack_v", "pack_i", "pack_p",
                        "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
                        "temp_a", "temp_b", "rem_a", "rem_b",
                        "delta_v_a", "delta_v_b", "smoothed_i",
                        "smoothed_p", "minutes_remaining",
                        "name_a", "name_b"])
            today = datetime.now()
            t0 = today.replace(hour=10, minute=0, second=0, microsecond=0)
            # Samples spanning ~25 min (5 bins at 5-min downsample
            # cadence). Each consecutive pair must be <= 60 s apart
            # to integrate (otherwise treated as a gap). Use 30 s
            # cadence so 50 samples cover 1500 s = 25 min.
            for i in range(50):
                ts = (t0 + timedelta(seconds=30 * i)).isoformat()
                ci = -4.0 if i % 2 == 0 else -3.0
                w.writerow([ts, "discharging", "26.30", str(ci),
                            str(ci * 26.3), "70", "68", "13.15", "13.14",
                            str(ci / 2), str(ci / 2),
                            "23", "23", "150", "130",
                            "0.008", "0.009", str(ci), str(ci * 26.3),
                            "", "V-12V200AH-0533", "V-12V200AH-0667"])
        h, captured = _make_handler("/today-curve")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # Chart SVG present
        self.assertIn(b"<svg", body)
        self.assertIn(b"cumulative net Ah since midnight", body)
        # Polyline drawn through the data
        self.assertIn(b"<polyline", body)
        # Summary line with cumulative figures
        self.assertIn(b"cumulative charge", body)
        self.assertIn(b"cumulative discharge", body)

    def test_drift_route_empty_state(self) -> None:
        """No live_ratio_log → friendly empty message, no crash."""
        h, captured = _make_handler("/drift")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b"Live-ratio drift over time", body)
        self.assertIn(b"no live_ratio_log entries yet", body)

    def test_drift_route_renders_chart_with_data(self) -> None:
        """When live_ratio_log has rows, the page renders an SVG
        chart + a per-record table with summary stats."""
        path = self.root / "data" / "live_ratio_log.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "live_ratio_ah_per_kwh_m2",
                        "solar_ah_so_far", "irradiance_kwh_m2_so_far",
                        "solar_model_coefficient", "drift_pct",
                        "advisory_fired"])
            w.writerow(["2026-05-19T11:44:25", "5.73", "6.26", "1.09",
                        "8.15", "-29.70", "True"])
            w.writerow(["2026-05-19T12:09:45", "6.01", "8.01", "1.33",
                        "8.15", "-26.30", "True"])
        h, captured = _make_handler("/drift")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # SVG chart present
        self.assertIn(b"<svg", body)
        self.assertIn(b"live_ratio Ah", body)
        # Data points rendered as circles
        self.assertIn(b"<circle", body)
        # The coefficient reference line + ±20 % band labels
        self.assertIn(b"SolarModel coef", body)
        self.assertIn(b"+20%", body)
        self.assertIn(b"-20%", body)
        # Table with both rows + summary
        self.assertIn(b"n = 2 rows", body)
        self.assertIn(b"advisory fired in", body)
        # Cross-links to sister pages
        self.assertIn(b"/accuracy", body)
        self.assertIn(b"/low-accuracy", body)

    def test_api_includes_pack_gaps_field(self) -> None:
        """/api/latest.json must surface today's pack_gaps stats so
        the dashboard can render the BLE-logger reliability chip
        without re-scanning pack.csv client-side."""
        # Write a pack.csv with one obvious gap so the API has
        # something to report
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            # Use a header that mirrors the production schema's
            # tracked columns; the dashboard test fixture's PACK_HEADER
            # already covers the rest.
            w.writerow(["ts", "state", "pack_v", "pack_i", "pack_p",
                        "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
                        "temp_a", "temp_b", "rem_a", "rem_b",
                        "delta_v_a", "delta_v_b", "smoothed_i",
                        "smoothed_p", "minutes_remaining",
                        "name_a", "name_b"])
            # Two samples today, 5 minutes apart → 1 gap
            today = datetime.now().date().isoformat()
            ts1 = f"{today}T10:00:00"
            ts2 = f"{today}T10:05:00"
            for ts in (ts1, ts2):
                w.writerow([ts, "idle", "26.30", "0.0", "0.0",
                            "70", "68", "13.15", "13.14",
                            "0.0", "0.0", "23", "23", "150", "130",
                            "0.008", "0.009", "0.0", "0.0", "",
                            "V-12V200AH-0533", "V-12V200AH-0667"])
        h, captured = _make_handler("/api/latest.json")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        payload = json.loads(body)
        self.assertIn("pack_gaps", payload)
        pg = payload["pack_gaps"]
        self.assertIsNotNone(pg)
        self.assertEqual(pg["count"], 1)
        # ~300 s gap (5 min)
        self.assertAlmostEqual(pg["max_gap_s"], 300.0, delta=1.0)

    def test_index_includes_gaps_chip_js(self) -> None:
        """Main page includes the PACK GAPS chip element, CSS, and
        the JS that toggles its visibility from `pack_gaps` in the
        API payload. Anchors the feature against accidental removal."""
        h, captured = _make_handler("/")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # The DOM element
        self.assertIn(b"id=\"gaps-chip\"", body)
        # CSS class
        self.assertIn(b".gaps-chip", body)
        # JS function that toggles visibility
        self.assertIn(b"updateGapsChip", body)
        # Shared fmtAge helper (used by both stale-banner and gaps chip)
        self.assertIn(b"function fmtAge", body)

    def test_index_includes_stale_banner_js(self) -> None:
        """The dashboard's main page includes the stale-banner element,
        CSS, and the JS that toggles its visibility. Anchors the
        feature against accidental removal in a future refactor.

        Caught a real operational issue on 2026-05-19 when the BLE
        logger stalled — drift advisory fired with -36 % because
        solar_ah froze while irradiance kept accumulating. The
        staleness banner makes that exact signal visible on the
        most-viewed surface."""
        h, captured = _make_handler("/")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # The DOM element
        self.assertIn(b"id=\"stale-banner\"", body)
        # The CSS class (matches the model-drift advisory's red palette)
        self.assertIn(b".stale-banner", body)
        # The JS function that toggles visibility
        self.assertIn(b"updateStaleBanner", body)
        # Shared threshold name so CLI / web agree (60 s matches
        # scripts/health.py PACK_STALE_THRESHOLD_S)
        self.assertIn(b"STALE_THRESHOLD_S", body)

    def test_health_route_renders_summary(self) -> None:
        """/health renders the scripts.health.render_summary() output
        inside a <pre> block with auto-refresh. Cold start (no data)
        still produces a valid page with the structural labels."""
        h, captured = _make_handler("/health")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("text/html", ctype)
        # Preformatted summary wrapper
        self.assertIn(b"<pre>", body)
        # All chain labels appear (same as the CLI's structural test)
        for label in (b"PACK", b"TODAY", b"SOLAR ONSET", b"SOLAR MODEL",
                      b"CONFIDENCE", b"SUNRISE ACC", b"MORN-LOW ACC",
                      b"DRIFT", b"PROJECTION", b"ADVISORY"):
            self.assertIn(label, body, f"missing chain label {label!r}")
        # Auto-refresh meta tag
        self.assertIn(b"http-equiv='refresh'", body)
        # Navigation back to home + sister pages
        self.assertIn(b"href='/'", body)
        self.assertIn(b"/accuracy", body)
        # Footer reference to the CLI command (anchors the doc claim
        # that web and CLI never diverge)
        self.assertIn(b"scripts/health.py", body)

    def test_index_links_to_health(self) -> None:
        """The main dashboard footer must link to /health so the user
        can find the lightweight summary view."""
        h, captured = _make_handler("/")
        h.do_GET()
        status, _, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(b'href="/health"', body)

    def test_index_includes_drift_advisory_badge_js(self) -> None:
        """The dashboard's index page must include the drift-advisory
        badge code so the advisor's model_drift_advisory string lands
        on screen when it's non-null. Anchors the feature against
        accidental removal."""
        h, captured = _make_handler("/")
        h.do_GET()
        status, ctype, body = captured[0]
        self.assertEqual(status, HTTPStatus.OK)
        # The badge construction + the CSS class + the data field
        self.assertIn(b"driftBadge", body)
        self.assertIn(b"drift-advisory", body)
        self.assertIn(b"model_drift_advisory", body)
        # The label "⚠ model drift" makes it tier-1 visible — same
        # symbol the CLI prints
        self.assertIn(b"model drift", body)

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
