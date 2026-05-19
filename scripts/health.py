"""One-screen Volthium system health summary.

Reads the latest state from every chain — pack, today's harvest,
solar onset cascade, SolarModel, accuracy validations, confidence
log, drift — and prints a compact tabular summary. Replaces the need
to invoke a dozen separate scripts when you just want "is the system
OK?".

Designed for terminal output (~80 cols, monochrome-safe). Each line
is one chain; the layout is intentionally fixed so visual scanning
across days highlights any value that's changed.

CLI:
    python scripts/health.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import calibration_log as cal_mod  # noqa: E402
import confidence_log as conf_mod  # noqa: E402
import projection_log as proj_mod  # noqa: E402
import projection_accuracy as acc_mod  # noqa: E402
import low_soc_accuracy as low_mod  # noqa: E402
import solar_onset as so_mod  # noqa: E402
import today_harvest as today_mod  # noqa: E402

PACK_CSV = Path("data/pack.csv")
WEATHER_CSV = Path("data/weather.csv")


def _last_pack_row() -> Optional[dict]:
    """Return the final row of pack.csv as a dict, or None."""
    if not PACK_CSV.exists():
        return None
    last: Optional[dict] = None
    with PACK_CSV.open() as f:
        for r in csv.DictReader(f):
            last = r
    return last


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _short_ts(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    return iso[11:16] if "T" in iso and len(iso) >= 16 else iso[:16]


def _fmt_pack_line(row: Optional[dict]) -> str:
    if not row:
        return "PACK         (no pack.csv yet)"
    soc_a = _f(row.get("soc_a"))
    soc_b = _f(row.get("soc_b"))
    pack_i = _f(row.get("pack_i"))
    smoothed_i = _f(row.get("smoothed_i"))
    pack_v = _f(row.get("pack_v"))
    state = (row.get("state") or "?").strip()
    soc_str = (f"{int(soc_a):d}/{int(soc_b):d}" if (soc_a is not None and soc_b is not None) else "—")
    i_str = (f"{pack_i:+.1f} A" if pack_i is not None else "—")
    smi_str = (f"smoothed {smoothed_i:+.1f} A" if smoothed_i is not None else "")
    v_str = (f"{pack_v:.2f} V" if pack_v is not None else "—")
    return (f"PACK         SOC {soc_str}  {state}  "
            f"{i_str}  {smi_str}  {v_str}")


def _fmt_today_line() -> str:
    try:
        snap = today_mod.snapshot(PACK_CSV, WEATHER_CSV)
    except Exception:
        return "TODAY        (snapshot failed)"
    ah_so_far = snap.get("solar_ah_so_far")
    ah_forecast = snap.get("solar_ah_forecast")
    pct = snap.get("pct_of_forecast")
    lr = snap.get("live_ratio_ah_per_kwh_m2")
    kwh_so_far = snap.get("irradiance_kwh_m2_so_far")
    # Cold start: pack.csv missing OR weather forecast missing
    if ah_so_far is None or ah_forecast is None:
        return "TODAY        (no harvest data yet)"
    pct_str = f"{pct:.0f}%" if pct is not None else "—"
    lr_str = (f"live_ratio {lr:.2f}" if lr is not None
              else f"live_ratio — (kWh/m² {kwh_so_far:.2f})" if kwh_so_far is not None
              else "live_ratio —")
    return (f"TODAY        solar {ah_so_far:+.1f} Ah / "
            f"{ah_forecast:.1f} forecast ({pct_str})  {lr_str}")


def _fmt_solar_onset_line() -> str:
    today_str = datetime.now().date().isoformat()
    records = so_mod.read_log()
    today_rec = next((r for r in records if r.date == today_str), None)
    if today_rec is None or today_rec.is_empty():
        return f"SOLAR ONSET  ({today_str}: pre-onset, no milestones yet)"
    parts = [
        f"zero {_short_ts(today_rec.first_zero_iso)}" if today_rec.first_zero_iso else None,
        f"idle {_short_ts(today_rec.first_idle_iso)}" if today_rec.first_idle_iso else None,
        f"pos {_short_ts(today_rec.first_positive_iso)}" if today_rec.first_positive_iso else None,
        f"net+ {_short_ts(today_rec.first_net_positive_iso)}" if today_rec.first_net_positive_iso else None,
    ]
    cascade = " → ".join(p for p in parts if p)
    soc_tail = ""
    if today_rec.soc_avg_at_net_positive is not None:
        soc_tail = f"  SOC {today_rec.soc_avg_at_net_positive:.1f}%"
    return f"SOLAR ONSET  {cascade}{soc_tail}"


def _fmt_solar_model_line() -> str:
    entries = cal_mod.read_log()
    if not entries:
        return "SOLAR MODEL  (no calibration_log entries yet)"
    e = entries[-1]
    return (f"SOLAR MODEL  coef {e.coefficient:.3f}  "
            f"({e.n_observations} obs, {e.confidence} conf, "
            f"fit {e.ts[:16]})")


def _fmt_confidence_line() -> str:
    entries = conf_mod.read_log()
    if not entries:
        return "CONFIDENCE   (no transitions logged yet)"
    e = entries[-1]
    lifted = "lifted" if e.lifted else "not lifted"
    ae = (f"±{e.recent_abs_error_pp:.2f} pp" if e.recent_abs_error_pp is not None
          else "—")
    return (f"CONFIDENCE   {e.base} → {e.resolved}  {lifted}  "
            f"n={e.recent_n} {ae}")


def _fmt_accuracy_line(label: str,
                      summary: dict,
                      latest_err: Optional[float] = None) -> str:
    if not summary or summary.get("n", 0) == 0:
        return f"{label:<12} (no validatable records yet)"
    n = summary["n"]
    mean = summary["mean_error"]
    abs_e = summary["mean_abs_error"]
    lo = summary["min_error"]
    hi = summary["max_error"]
    latest = ""
    if latest_err is not None:
        latest = f"  latest {latest_err:+.1f}"
    return (f"{label:<12} n={n}, mean {mean:+.2f} pp, abs {abs_e:.2f}  "
            f"[{lo:+.1f}..{hi:+.1f}]{latest}")


def _fmt_drift_line(latest_proj: Optional[proj_mod.LogEntry]) -> str:
    """Compute current drift from the latest harvest snapshot + the
    SolarModel's current coefficient."""
    try:
        snap = today_mod.snapshot(PACK_CSV, WEATHER_CSV)
    except Exception:
        snap = {}
    lr = snap.get("live_ratio_ah_per_kwh_m2")
    coef = latest_proj.solar_model_coefficient if latest_proj else None
    if lr is None or coef is None or coef <= 0:
        return "DRIFT        (live_ratio pending or no model fit)"
    drift = (lr - coef) / coef * 100.0
    flag = "⚠ advisory" if abs(drift) >= 20.0 else "within threshold"
    return (f"DRIFT        {drift:+.1f}% "
            f"(live {lr:.2f} vs model {coef:.2f}) — {flag}")


def _fmt_projection_and_advisory(latest_proj: Optional[proj_mod.LogEntry]) -> tuple[str, str]:
    if latest_proj is None:
        return ("PROJECTION   (no projection_log entries yet)", "ADVISORY     (no recommendation)")
    proj_line = (
        f"PROJECTION   start {latest_proj.start_soc_pct:.1f} → "
        f"sunrise {latest_proj.projected_sunrise_soc:.1f} → "
        f"low {latest_proj.projected_low_soc:.1f} → "
        f"eve {latest_proj.projected_tomorrow_evening_soc:.1f} (next 24h)"
    )
    # Re-run the advisor's verdict via a fresh invocation would be expensive;
    # instead reuse the harvest snap's "is the projected low above comfort?" check.
    # Comfort floor default is 25 %.
    if latest_proj.projected_low_soc < 25.0:
        adv_line = (f"ADVISORY     ▶ RUN GENERATOR  "
                    f"projected low {latest_proj.projected_low_soc:.0f}% "
                    f"below 25% comfort floor")
    elif latest_proj.projected_low_soc < 50.0:
        adv_line = (f"ADVISORY     ⚠ morning watch  "
                    f"projected low {latest_proj.projected_low_soc:.0f}%")
    else:
        adv_line = (f"ADVISORY     ✓ no generator needed  "
                    f"projected low {latest_proj.projected_low_soc:.0f}%")
    return proj_line, adv_line


def render_summary() -> str:
    """Build the full summary text. Returns the multi-line string."""
    now = datetime.now()
    lines: list[str] = []
    lines.append(f"=== Volthium pack health summary "
                 f"({now:%Y-%m-%d %H:%M}) ===")
    lines.append("")
    lines.append(_fmt_pack_line(_last_pack_row()))
    lines.append(_fmt_today_line())
    lines.append(_fmt_solar_onset_line())
    lines.append("")
    lines.append(_fmt_solar_model_line())
    lines.append(_fmt_confidence_line())
    # Sunrise accuracy
    try:
        all_proj = proj_mod.read_log()
        pack_samples = acc_mod._load_pack_samples(PACK_CSV)
        sunrise_records = acc_mod.compute_accuracy_records(all_proj, pack_samples)
    except Exception:
        sunrise_records = []
    s_sum = acc_mod.summarize(sunrise_records) if sunrise_records else {}
    latest_sunrise_err = (sunrise_records[-1].error_pct_points
                          if sunrise_records else None)
    lines.append(_fmt_accuracy_line("SUNRISE ACC", s_sum, latest_sunrise_err))
    # Morning-low accuracy
    try:
        onsets = so_mod.read_log()
        low_records = low_mod.compute_accuracy_records(all_proj, onsets)
    except Exception:
        low_records = []
    l_sum = low_mod.summarize(low_records) if low_records else {}
    latest_low_err = (low_records[-1].error_pct_points
                      if low_records else None)
    lines.append(_fmt_accuracy_line("MORN-LOW ACC", l_sum, latest_low_err))
    latest_proj = all_proj[-1] if all_proj else None
    lines.append(_fmt_drift_line(latest_proj))
    lines.append("")
    proj_line, adv_line = _fmt_projection_and_advisory(latest_proj)
    lines.append(proj_line)
    lines.append(adv_line)
    return "\n".join(lines) + "\n"


def main() -> int:
    print(render_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
