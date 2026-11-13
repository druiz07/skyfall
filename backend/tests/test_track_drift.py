from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from skyfall.config import DispersionConfig
from skyfall.orbit import ground_track
from skyfall.sources.demo import demo_reentries
from skyfall.track_drift import (
    AGE_LABELS,
    age_bucket,
    drift_model,
    drift_table,
    element_age_hours,
    measure_drift,
    with_track_drift,
)

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _notice():
    return next(n for n in demo_reentries(REF) if n.norad_id == 900001)


def test_age_buckets():
    assert [age_bucket(h) for h in (0, 5.9, 6, 30, 60, 100, 500)] == [0, 0, 1, 3, 4, 5, 6]


def test_drift_table_is_monotone_and_ignores_lost_tracks():
    ages = [3, 9, 18, 36, 60, 96, 200]
    # Invented: drift 10 km per bucket step, except a younger-looking bucket 4.
    samples = [(a, 10.0 * (i + 1) * (0.2 if i == 4 else 1.0)) for i, a in enumerate(ages) for _ in range(20)]
    samples += [(200, 5000.0)] * 5  # lost: timing, not sideways
    table = drift_table(samples)
    sigmas = [b["sigma_km"] for b in table["buckets"]]
    assert [b["age"] for b in table["buckets"]] == list(AGE_LABELS)
    assert sigmas == sorted(sigmas)
    assert table["buckets"][6]["n_lost"] == 5
    assert table["buckets"][6]["p90_km"] == pytest.approx(70.0)


def test_shipped_model_grows_with_age():
    model = drift_model()
    assert model.sigma_km(3) < model.sigma_km(36) < model.sigma_km(100)


def test_with_track_drift_widens_once_and_can_be_switched_off():
    notice = _notice()
    base = DispersionConfig()
    widened = with_track_drift(notice, base)
    drift = drift_model().sigma_km(element_age_hours(notice))
    assert widened.cross_sigma_km == pytest.approx(np.hypot(base.cross_sigma_km, drift))
    assert with_track_drift(notice, widened) == widened  # never applied twice
    off = replace(base, track_drift=False)
    assert with_track_drift(notice, off) == off


def test_measure_drift_is_zero_on_the_track_and_grows_off_it():
    notice = _notice()
    track = ground_track(notice.elements, notice.decay_epoch, np.array([0.0]))
    truth = notice.model_copy(
        update={
            "issued_at": notice.decay_epoch + timedelta(hours=1),
            "predicted_lat": float(track.lat_deg[0]),
            "predicted_lon": float(track.lon_deg[0]),
        }
    )
    assert measure_drift(notice, truth) < 2.0
    # 1 deg of latitude off a 53 deg-inclined track: ~67 km sideways.
    moved = truth.model_copy(update={"predicted_lat": truth.predicted_lat + 1.0})
    assert 40.0 < measure_drift(notice, moved) < 112.0
