from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from skyfall.orbit import ground_track
from skyfall.sources.demo import demo_reentries
from skyfall.validation import confirmation, hindcast_all, zone_check

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
NAMES = ["skyfall_99", "skyfall_95", "skyfall_90", "skyfall_uniform_99", "easa_70km", "easa_120km"]


def _notice():
    return next(n for n in demo_reentries(REF) if n.norad_id == 900001)


def _confirmed(notice, minutes_late: float):
    """An invented 'it is down' notice: on the ground track, minutes_late after DECAY_EPOCH."""
    track = ground_track(notice.elements, notice.decay_epoch, np.array([minutes_late]))
    down = notice.decay_epoch + timedelta(minutes=minutes_late)
    return notice.model_copy(
        update={
            "decay_epoch": down,
            "window_minutes": 1.0,
            "issued_at": down + timedelta(hours=2),
            "predicted_lat": float(track.lat_deg[0]),
            "predicted_lon": float(track.lon_deg[0]),
        }
    )


def test_confirmation_is_the_newest_notice_issued_after_its_own_decay():
    notice = _notice()
    early, late = _confirmed(notice, 0.0), _confirmed(notice, 1.0)
    late = late.model_copy(update={"issued_at": early.issued_at + timedelta(hours=1)})
    assert confirmation([notice]) is None  # a forecast is not a confirmation
    assert confirmation([notice, late, early]) is late


def test_zone_check_hit_and_miss_distance():
    mask = np.zeros((360, 720), dtype=bool)
    mask[180, 360] = True  # cell [0, 0.5) x [0, 0.5), centre (0.25, 0.25)
    assert zone_check("x", mask, 0.5, 0.1, 0.4).hit
    miss = zone_check("x", mask, 0.5, 0.25, 10.25)  # 10 deg east along the equator
    assert not miss.hit
    assert miss.miss_km == pytest.approx(1112, rel=0.01)


def test_hindcast_point_on_track_inside_window_is_caught_by_every_zone():
    notice = _notice()
    (h,) = hindcast_all([notice, _confirmed(notice, 10.0)])
    assert h.z == pytest.approx(10.0 / notice.window_minutes)
    assert [z.name for z in h.zones] == NAMES
    assert all(z.hit and z.miss_km == 0.0 for z in h.zones)


def test_hindcast_late_reentry_escapes_the_window_closures():
    # 2.5 windows late (~1.2 laps): a pass ~2000 km from anything the strips
    # cover. Not 3: +-43 min spans almost a lap, so some lateness lands back
    # on a covered stretch by chance.
    notice = _notice()
    (h,) = hindcast_all([notice, _confirmed(notice, 2.5 * notice.window_minutes)])
    zones = {z.name: z for z in h.zones}
    for name in ("skyfall_uniform_99", "easa_70km", "easa_120km"):
        assert not zones[name].hit
        assert zones[name].miss_km > 500
    assert zones["skyfall_99"].hit  # the empirical tail reaches it


def test_hindcast_can_skip_the_uniform_zone():
    notice = _notice()
    (h,) = hindcast_all([notice, _confirmed(notice, 10.0)], include_uniform=False)
    assert [z.name for z in h.zones] == [n for n in NAMES if n != "skyfall_uniform_99"]
