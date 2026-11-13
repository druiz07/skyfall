import math

from fastapi.testclient import TestClient

from skyfall import api
from skyfall.api import app

client = TestClient(app)


def _km(a, b):
    (lat1, lon1), (lat2, lon2) = (map(math.radians, p) for p in (a, b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def test_track_spans_exactly_the_notice_window():
    body = client.get("/reentries/900001/track").json()  # +-43 min, a point every 30 s

    assert body["step_seconds"] == 30
    assert len(body["points"]) == 2 * 43 * 2 + 1
    assert all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in body["points"])


def test_demo_impact_point_is_the_orbit_at_decay_epoch():
    body = client.get("/reentries/900001/track").json()

    impact = body["impact"]
    assert impact["source"] == "orbit"
    middle = body["points"][len(body["points"]) // 2]
    assert _km((impact["lat"], impact["lon"]), middle) < 1.0


def test_impact_point_comes_from_the_tip_when_it_has_one(monkeypatch):
    notice = api._notices()[900001].model_copy(update={"predicted_lat": -48.4, "predicted_lon": -115.2})
    monkeypatch.setattr(api, "_notices", lambda: {900001: notice})

    impact = client.get("/reentries/900001/track").json()["impact"]

    assert (impact["lat"], impact["lon"], impact["source"]) == (-48.4, -115.2, "tip")


def test_unknown_object_gives_404():
    assert client.get("/reentries/1/track").status_code == 404
