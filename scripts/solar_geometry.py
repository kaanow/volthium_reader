"""Where the sun is, from the clock alone. No sensor, no network, no imports
beyond the standard library's math and time.

Extracted from xanbus_latch_guard.py on 2026-08-09 so the live telemetry
decoder can use it too. It is deliberately its own module rather than an
import from the guard: the guard mutates sys.path and pulls in xanbus_node,
socket and subprocess, and dragging a CAN-node dependency chain into the
long-running service that decodes all solar telemetry — on a 1 GB Pi — is a
bad trade for fifteen lines of arithmetic.

Why anything here needs the sun's position at all: the MPPT diode-clamp
detector keys on the array sitting a diode drop above the battery. At dusk the
array passes through exactly that voltage on its way down, and worse, the MPPT
*hunts* — repeatedly trying to start, pulling the array to battery voltage,
failing, and releasing it back to open circuit. On 2026-08-09 a single 60 s
bucket at 20:19 local held pv_v min 26.81 and max 89.74. Individual samples in
that window are indistinguishable from a real clamp.

That is not hypothetical: on 2026-08-06 the guard bounced the MPPT at 21:01
local, sun elevation -3.6 deg (commit 26010b1, "it bounced the MPPT at
night"). Elevation is the discriminator that voltage cannot be.
"""
from __future__ import annotations

import math
import time

# The Barge Inn, Loon Lake.
SITE_LAT, SITE_LON = 51.11935280004921, -121.20969152967822

# Below this the array may be passing through clamp-like voltages purely
# because it is getting dark. 5 deg, not 10: at 51.12 N the midwinter sun
# peaks at 15.4 deg and clears 10 deg for only 4.4 h against 6.2 h above 5 deg,
# so a 10 deg gate would blind everything through the darkest months — when a
# latch is most expensive because there is so little daylight to lose.
MIN_SUN_ELEVATION_DEG = 5.0


def sun_elevation_deg(when: float | None = None) -> float:
    """Solar elevation at the site, degrees above the horizon.

    Low-precision NOAA-style solar position: good to a fraction of a degree,
    which is far finer than the gate needs. Deliberately depends on
    nothing but the clock — no sensor, no network, no bus.
    """
    ts = time.time() if when is None else when
    utc = time.gmtime(ts)
    doy = utc.tm_yday
    hour = utc.tm_hour + utc.tm_min / 60 + utc.tm_sec / 3600
    decl = math.radians(23.44) * math.sin(math.radians(360 / 365 * (doy - 81)))
    b = math.radians(360 / 364 * (doy - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    true_solar = hour * 60 + 4 * SITE_LON + eot
    hour_angle = math.radians(true_solar / 4 - 180)
    lat = math.radians(SITE_LAT)
    sin_el = (math.sin(lat) * math.sin(decl)
              + math.cos(lat) * math.cos(decl) * math.cos(hour_angle))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def is_daylight(when: float | None = None) -> bool:
    """True when the sun is high enough that a clamp-like array voltage means
    a clamp, not dusk."""
    return sun_elevation_deg(when) >= MIN_SUN_ELEVATION_DEG
