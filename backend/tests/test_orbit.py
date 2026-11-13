from datetime import datetime, timezone

import numpy as np
import pytest

from skyfall.orbit import ecef_to_geodetic, gmst_rad, ground_track, to_julian
from skyfall.sources.demo import demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _notice(norad_id):
    return next(n for n in demo_reentries(REF) if n.norad_id == norad_id)


def test_gmst_at_j2000_matches_reference_value():
    # 2000-01-01 12:00 UT: GMST = 280.46061837 deg (IAU 1982)
    jd, fr = to_julian(datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert np.degrees(gmst_rad(jd, fr)) == pytest.approx(280.46061837, abs=1e-6)


@pytest.mark.parametrize(
    "xyz, lat, lon, alt",
    [
        ((6378.137, 0.0, 0.0), 0.0, 0.0, 0.0),
        ((0.0, 6378.137, 0.0), 0.0, 90.0, 0.0),
        ((0.0, 0.0, 6356.752314245), 90.0, 0.0, 0.0),
    ],
)
def test_ecef_to_geodetic_known_points(xyz, lat, lon, alt):
    got_lat, got_lon, got_alt = ecef_to_geodetic(np.array([xyz]))
    assert got_lat[0] == pytest.approx(lat, abs=1e-9)
    assert got_lon[0] == pytest.approx(lon, abs=1e-9)
    assert got_alt[0] == pytest.approx(alt, abs=1e-6)


@pytest.mark.parametrize("norad_id, max_lat", [(900001, 53.0), (900002, 180.0 - 97.6)])
def test_latitude_never_exceeds_inclination(norad_id, max_lat):
    # A satellite only flies over latitudes up to its inclination
    # (or 180 - inclination for retrograde orbits like sun-synchronous ones).
    notice = _notice(norad_id)
    offsets = np.linspace(0.0, 1440.0, 2000)
    track = ground_track(notice.elements, notice.decay_epoch, offsets)

    assert track.ok.all()
    peak = np.abs(track.lat_deg).max()
    # Geodetic latitude is slightly above geocentric (Earth is flattened): allow 0.3 deg.
    assert max_lat - 0.5 < peak < max_lat + 0.3


def test_one_orbit_later_track_shifts_west():
    # While the satellite completes one lap (~88 min), Earth turns ~22 deg under it.
    notice = _notice(900001)
    period_min = 1440.0 / notice.elements.mean_motion_rev_per_day
    track = ground_track(notice.elements, notice.decay_epoch, np.array([0.0, period_min]))

    assert track.lat_deg[1] == pytest.approx(track.lat_deg[0], abs=1.0)
    shift = (track.lon_deg[1] - track.lon_deg[0] + 180.0) % 360.0 - 180.0
    expected = -360.0 * period_min / 1436.07  # sidereal day = 1436.07 min
    assert shift == pytest.approx(expected, abs=1.0)


def test_altitude_matches_demo_orbit():
    notice = _notice(900001)
    track = ground_track(notice.elements, notice.decay_epoch, np.linspace(0, 180, 50))
    assert np.all((track.alt_km > 170.0) & (track.alt_km < 230.0))
