from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from skyfall import api
from skyfall.api import app
from skyfall.orbit import ground_track
from skyfall.sources.demo import demo_history, demo_reentries
from tests.test_api_track import _km

client = TestClient(app)
REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_demo_series_ends_with_the_live_notice():
    series = demo_history(900001, REF)
    live = {n.norad_id: n for n in demo_reentries(REF)}[900001]

    assert series[-1] == live
    assert [n.window_minutes for n in series] == sorted((n.window_minutes for n in series), reverse=True)
    assert all(a.issued_at < b.issued_at for a, b in zip(series, series[1:]))
    # Elements are a little older than each notice, like real TIPs.
    assert all(n.elements.epoch < n.issued_at for n in series)


def test_rewound_elements_keep_the_same_ground_track():
    series = demo_history(900001, REF)
    t, offsets = series[-1].decay_epoch, [0.0]
    final = ground_track(series[-1].elements, t, offsets)
    for n in series[:-1]:
        hours = (series[-1].issued_at - n.issued_at) / timedelta(hours=1)
        old = ground_track(n.elements, t, offsets)
        gap = _km((final.lat_deg[0], final.lon_deg[0]), (old.lat_deg[0], old.lon_deg[0]))
        assert gap < 3 * hours + 10  # a few km per hour of age, never a different orbit


def test_other_demo_objects_have_a_single_notice_and_unknown_ones_none():
    assert len(demo_history(900002, REF)) == 1
    assert demo_history(12345, REF) == []


def test_history_endpoint_lists_notices_oldest_first():
    body = client.get("/reentries/900001/history").json()

    assert body["norad_id"] == 900001
    assert [n["index"] for n in body["notices"]] == list(range(len(body["notices"])))
    assert [n["window_minutes"] for n in body["notices"]] == [900, 300, 120, 60, 43]
    assert body["landed"] is None  # the demo object has not fallen yet


def test_unknown_object_has_no_history():
    assert client.get("/reentries/12345/history").status_code == 404


class FakeHistoryClient:
    def __init__(self, notices):
        self.notices = notices

    def notice_history(self, norad_id):
        return self.notices


def test_space_track_confirmation_becomes_the_landing_not_a_frame(monkeypatch):
    # Invented orbit dressed up as a real series: two forecasts, then "it is down".
    series = [n.model_copy(update={"source": "spacetrack"}) for n in demo_history(900001, REF)[-2:]]
    fell_at = series[-1].decay_epoch - timedelta(minutes=17)
    down = series[-1].model_copy(
        update={
            "decay_epoch": fell_at,
            "window_minutes": 1.0,
            "issued_at": fell_at + timedelta(hours=2),
            "predicted_lat": -16.5,
            "predicted_lon": -156.9,
        }
    )
    monkeypatch.setattr(api, "_client", lambda: FakeHistoryClient([series[1], down, series[0]]))

    body = TestClient(app).get("/reentries/900001/history").json()

    assert [n["window_minutes"] for n in body["notices"]] == [60, 43]  # sorted, no confirmation
    assert body["landed"] == {"decay_epoch": fell_at.isoformat().replace("+00:00", "Z"), "lat": -16.5, "lon": -156.9}


def test_history_zone_of_one_notice_and_404_past_the_end():
    body = client.get("/reentries/900001/history/4/corridor").json()  # +-43 min, quick

    assert body["regions"]["99"]["area_km2"] > 0
    assert client.get("/reentries/900001/history/9/corridor").status_code == 404
    assert len(client.get("/reentries/900001/history/3/track").json()["points"]) == 2 * 60 * 2 + 1


def test_real_zones_are_stored_on_disk_and_read_back(monkeypatch, tmp_path):
    series = [n.model_copy(update={"source": "spacetrack"}) for n in demo_history(900001, REF)[-1:]]
    monkeypatch.setattr(api, "_client", lambda: FakeHistoryClient(series))
    monkeypatch.setattr(api, "ZONE_CACHE_DIR", tmp_path)
    web = TestClient(app)

    first = web.get("/reentries/900001/history/0/corridor").json()
    assert len(list(tmp_path.glob("900001_*.json"))) == 1

    def must_not_recompute(notice):
        raise AssertionError("zone recomputed instead of read from disk")

    monkeypatch.setattr(api, "_corridor", must_not_recompute)
    assert web.get("/reentries/900001/history/0/corridor").json() == first
