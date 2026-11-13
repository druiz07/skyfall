"""API on Space-Track data, with a fake client instead of the network."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from skyfall import api
from skyfall.sources.demo import demo_reentries
from skyfall.sources.spacetrack import SpaceTrackError

ISSUED = datetime(2030, 1, 10, 12, 0, tzinfo=timezone.utc)


def _real_like(window_minutes, issued_at=ISSUED):
    # Invented orbit (demo), dressed up as a Space-Track notice.
    return demo_reentries(datetime(2030, 1, 10, tzinfo=timezone.utc))[0].model_copy(
        update={"source": "spacetrack", "window_minutes": window_minutes, "issued_at": issued_at}
    )


class FakeClient:
    def __init__(self, *batches):
        self.batches = list(batches)

    def latest_notices(self):
        batch = self.batches[0] if len(self.batches) == 1 else self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return batch


@pytest.fixture
def use_client(monkeypatch):
    def install(fake):
        monkeypatch.setattr(api, "_client", lambda: fake)
        return TestClient(api.app)

    return install


def test_health_and_reentries_report_space_track(use_client):
    client = use_client(FakeClient([_real_like(60)]))

    assert client.get("/health").json()["source"] == "spacetrack"
    [summary] = client.get("/reentries").json()
    assert summary["source"] == "spacetrack"
    assert summary["issued_at"] == "2030-01-10T12:00:00Z"


def test_new_notice_for_the_same_object_is_recomputed(use_client):
    old = _real_like(120)
    new = _real_like(150, issued_at=ISSUED.replace(hour=18))
    client = use_client(FakeClient([old], [old], [new]))
    norad = old.norad_id

    first = client.get(f"/reentries/{norad}/corridor").json()
    again = client.get(f"/reentries/{norad}/corridor").json()
    updated = client.get(f"/reentries/{norad}/corridor").json()

    assert again == first
    assert updated["n_samples"] > first["n_samples"]  # wider window, more samples


def test_space_track_unavailable_gives_503(use_client):
    client = use_client(FakeClient(SpaceTrackError("Space-Track request failed: down")))

    response = client.get("/reentries")

    assert response.status_code == 503
    assert "down" in response.json()["detail"]


def test_reentries_flag_objects_that_already_fell(use_client):
    coming = _real_like(60)
    coming = coming.model_copy(update={"issued_at": coming.decay_epoch - timedelta(hours=3)})
    # Confirmation: issued after its own DECAY_EPOCH, with the point where it came down.
    fell = coming.model_copy(
        update={
            "norad_id": coming.norad_id + 1,
            "window_minutes": 1,
            "issued_at": coming.decay_epoch + timedelta(hours=2),
            "predicted_lat": -16.5,
            "predicted_lon": -156.9,
        }
    )
    client = use_client(FakeClient([coming, fell]))

    landed = {s["norad_id"]: s["landed"] for s in client.get("/reentries").json()}

    assert landed == {coming.norad_id: False, fell.norad_id: True}
