from datetime import datetime, timezone

import numpy as np
import pytest

from skyfall.closure import precautionary_mask, window_track
from skyfall.density import cell_areas_km2
from skyfall.dispersion import EARTH_RADIUS_KM
from skyfall.sources.demo import demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
FINE = 0.1  # fine grid so geometry checks are not dominated by cell size


def _area(mask, res):
    return float(cell_areas_km2(res)[mask].sum())


def _notice(norad_id):
    return next(n for n in demo_reentries(REF) if n.norad_id == norad_id)


@pytest.mark.parametrize("lat, lon", [(0.0, 0.0), (45.0, 179.95), (89.9, 10.0)])
def test_single_point_closes_a_disc(lat, lon):
    # Equator, antimeridian and pole: always a ~100 km radius disc.
    mask = precautionary_mask(np.array([lat]), np.array([lon]), 100.0, FINE)
    assert _area(mask, FINE) == pytest.approx(np.pi * 100.0**2, rel=0.08)


def test_straight_track_closes_a_strip():
    # 20 deg of equator, 100 km each side: rectangle plus two half-discs at the ends.
    lon = np.linspace(-10.0, 10.0, 400)
    mask = precautionary_mask(np.zeros_like(lon), lon, 100.0, FINE)
    length = EARTH_RADIUS_KM * np.radians(20.0)
    assert _area(mask, FINE) == pytest.approx(length * 200.0 + np.pi * 100.0**2, rel=0.03)


def test_window_track_spans_the_whole_window():
    notice = _notice(900001)
    lat, lon = window_track(notice, margin_min=0.0, step_s=60.0)
    assert len(lat) == 2 * 43 + 1  # one point per minute, both ends included
    lat, lon = window_track(notice, margin_min=5.0, step_s=60.0)
    assert len(lat) == 2 * 48 + 1  # EASA's "few minutes before and after"
    assert np.abs(lat).max() <= 53.5  # never beyond the orbit inclination


def test_wider_strip_and_longer_window_close_more():
    short = _notice(900001)
    long_ = _notice(900003)
    areas = {
        (n.norad_id, hw): _area(precautionary_mask(*window_track(n), hw, 0.5), 0.5)
        for n in (short, long_)
        for hw in (70.0, 120.0)
    }
    assert areas[(900001, 70.0)] < areas[(900001, 120.0)]
    assert areas[(900001, 120.0)] < areas[(900003, 120.0)]
