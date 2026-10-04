"""The site's local time, derived from its timezone rather than assumed.

Eight analysis scripts each hardcoded `LOCAL_OFFSET_H = -7`, which is PDT.
Every one of them becomes wrong by an hour on 2026-11-01 when the site goes to
PST, and wrong again every spring and autumn thereafter.

These are READ-ONLY tools, so the consequence is misattribution rather than
data loss — but misattribution is exactly how the 1356 Wh wrong-day bug
happened: the MPPT's daily counter resets at 06:18-07:50 UTC, which is
23:18-00:50 PDT, already straddling local midnight. A one-hour shift moves
that reset across the date boundary, and `mppt_day()` takes max(day_ah) over a
window whose edge is already within ~40 minutes of it.

SITE_TZ matches cloud/server/db.py's constant, which exists for the same
reason: the site's zone is a physical fact about where the panels are, not a
display preference.
"""

from __future__ import annotations

import datetime as dt

SITE_TZ = "America/Vancouver"
# Identical Pacific DST rules, used only if SITE_TZ does not resolve correctly.
_EQUIVALENT_TZ = "America/Los_Angeles"
_FALLBACK_OFFSET_H = -8                # PST: the standard offset, not the DST one


def _pick_tz():
    """Return a zone that actually OBSERVES Pacific DST, and say which.

    DO NOT TRUST THE NAME. On both this laptop and the Pi (checked
    2026-10-04), `ZoneInfo("America/Vancouver")` resolves to a zone reporting
    MST -0700 in January AND July — Vancouver is never MST, and a zone with no
    summer/winter difference is not Pacific at all. `America/Los_Angeles`
    resolves correctly on the same machines, so the tz database is present but
    that one entry is wrong or aliased oddly.

    Shipping a DST helper on top of that would have replaced a hardcoded -7
    with a different constant wearing a timezone's clothes — the same bug,
    harder to see. So the zone is VALIDATED by checking that January and July
    differ, and falls back to the equivalent zone when it does not.

    Postgres is unaffected: it has its own tz database and resolves Vancouver
    correctly (verified — complete days report coverage exactly 1.0, so the
    ledger's day boundaries are 24 h apart). This is a Python-side problem
    only, which is why it had never shown up in the server.
    """
    try:
        from zoneinfo import ZoneInfo
    except Exception:                  # pragma: no cover - no zoneinfo
        return None, "none"
    for name in (SITE_TZ, _EQUIVALENT_TZ):
        try:
            tz = ZoneInfo(name)
        except Exception:
            continue
        jan = dt.datetime(2027, 1, 15, 20, tzinfo=dt.timezone.utc).astimezone(tz)
        jul = dt.datetime(2027, 7, 15, 20, tzinfo=dt.timezone.utc).astimezone(tz)
        if jan.utcoffset() != jul.utcoffset():
            return tz, name
    return None, "none"


_TZ, TZ_SOURCE = _pick_tz()


def local_offset_h(when: dt.datetime | float | None = None) -> float:
    """UTC offset in hours at `when`, honouring DST.

    Takes the instant because the answer CHANGES — that is the whole point.
    A module-level constant cannot express it.
    """
    if when is None:
        when = dt.datetime.now(dt.timezone.utc)
    elif isinstance(when, (int, float)):
        when = dt.datetime.fromtimestamp(when, dt.timezone.utc)
    elif when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    if _TZ is None:
        return _FALLBACK_OFFSET_H
    return when.astimezone(_TZ).utcoffset().total_seconds() / 3600


def to_local(when: dt.datetime) -> dt.datetime:
    """A UTC instant as site-local wall time, DST included."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(_TZ) if _TZ else when + dt.timedelta(
        hours=_FALLBACK_OFFSET_H)


def local_date(when: dt.datetime | float) -> dt.date:
    """The site-local calendar date of an instant."""
    if isinstance(when, (int, float)):
        when = dt.datetime.fromtimestamp(when, dt.timezone.utc)
    return to_local(when).date()
