"""TIP + gp_history -> ReentryNotice, with invented records (never real Space-Track data)."""

import io
import json
from datetime import datetime, timezone

import pytest

from skyfall.sources.spacetrack import (
    RateLimiter,
    SpaceTrackClient,
    SpaceTrackError,
    notice_from_tip,
    parse_gp,
    pick_elements,
)

ISSUED = datetime(2030, 1, 10, 12, 0, tzinfo=timezone.utc)


def _gp(epoch, created, mean_anomaly="10.0"):
    return {
        "OBJECT_NAME": "TEST-SAT",
        "EPOCH": epoch,
        "CREATION_DATE": created,
        "INCLINATION": "53.0",
        "RA_OF_ASC_NODE": "120.5",
        "ECCENTRICITY": "0.0002",
        "ARG_OF_PERICENTER": "90.0",
        "MEAN_ANOMALY": mean_anomaly,
        "MEAN_MOTION": "16.2",
        "BSTAR": "0.0005",
    }


TIP = {
    "NORAD_CAT_ID": "999999",
    "MSG_EPOCH": "2030-01-10 12:00:00",
    "DECAY_EPOCH": "2030-01-11 03:30:00",
    "WINDOW": "120",
    "LAT": "-20.5",
    "LON": "250.0",
}


def test_parse_gp_converts_strings_and_dates():
    el = parse_gp(_gp("2030-01-10T06:30:15.500000", "2030-01-10T08:00:00"))
    assert el.epoch == datetime(2030, 1, 10, 6, 30, 15, 500000, tzinfo=timezone.utc)
    assert (el.inclination_deg, el.raan_deg, el.mean_motion_rev_per_day) == (53.0, 120.5, 16.2)
    assert el.bstar == pytest.approx(0.0005)


def test_picks_newest_elements_before_the_notice():
    rows = [
        _gp("2030-01-09T10:00:00", "2030-01-09T12:00:00", "1.0"),
        _gp("2030-01-10T05:00:00", "2030-01-10T07:00:00", "2.0"),
        _gp("2030-01-10T14:00:00", "2030-01-10T16:00:00", "3.0"),  # snapshot after the notice
    ]
    assert pick_elements(rows, ISSUED)["MEAN_ANOMALY"] == "2.0"


def test_ignores_elements_published_after_the_notice():
    # Snapshot taken before the notice, but only published after it: not known yet.
    rows = [
        _gp("2030-01-09T10:00:00", "2030-01-09T12:00:00", "1.0"),
        _gp("2030-01-10T11:00:00", "2030-01-10T13:00:00", "2.0"),
    ]
    assert pick_elements(rows, ISSUED)["MEAN_ANOMALY"] == "1.0"


def test_no_known_elements_raises():
    rows = [_gp("2030-01-10T14:00:00", "2030-01-10T16:00:00")]
    with pytest.raises(SpaceTrackError, match="No element set"):
        pick_elements(rows, ISSUED)


def test_notice_from_tip():
    notice = notice_from_tip(TIP, [_gp("2030-01-10T05:00:00", "2030-01-10T07:00:00")])
    assert notice.norad_id == 999999
    assert notice.name == "TEST-SAT"
    assert notice.source == "spacetrack"
    assert notice.issued_at == ISSUED
    assert notice.decay_epoch == datetime(2030, 1, 11, 3, 30, tzinfo=timezone.utc)
    assert notice.window_minutes == 120.0
    assert (notice.predicted_lat, notice.predicted_lon) == (-20.5, -110.0)  # 250 -> -110
    assert notice.elements.epoch == datetime(2030, 1, 10, 5, 0, tzinfo=timezone.utc)


class RoutingOpener:
    """Fake server: TIP queries get TIP rows, gp_history queries get element sets."""

    def __init__(self, tips, gp_rows):
        self.urls, self.tips, self.gp_rows = [], tips, gp_rows

    def open(self, request, timeout):
        url = request.full_url
        self.urls.append(url)
        if url.endswith("/login"):
            body = '""'
        elif "/class/gp_history/" in url:
            body = json.dumps(self.gp_rows)
        else:
            body = json.dumps(self.tips)
        return io.BytesIO(body.encode())


def test_notice_history_uses_two_requests_and_no_future_elements(tmp_path):
    tips = [TIP, {**TIP, "MSG_EPOCH": "2030-01-11 00:00:00", "WINDOW": "45"}]
    gp_rows = [
        _gp("2030-01-10T05:00:00", "2030-01-10T07:00:00", "1.0"),
        _gp("2030-01-10T20:00:00", "2030-01-10T21:00:00", "2.0"),
    ]
    opener = RoutingOpener(tips, gp_rows)
    client = SpaceTrackClient(
        "user",
        "pw",
        cache_dir=tmp_path,
        limiter=RateLimiter(min_interval_s=0),
        opener=opener,
    )

    notices = client.notice_history(999999)

    assert len(opener.urls) == 3  # login + TIP series + one gp_history span
    assert "/EPOCH/2030-01-07--2030-01-12/" in opener.urls[2]
    assert [n.elements.mean_anomaly_deg for n in notices] == [1.0, 2.0]
    assert [n.window_minutes for n in notices] == [120.0, 45.0]
