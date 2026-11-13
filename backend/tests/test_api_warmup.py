import threading
import time

from fastapi.testclient import TestClient

from skyfall import api
from skyfall.sources.demo import demo_reentries


def test_a_zone_asked_twice_at_once_is_computed_once(monkeypatch):
    notice = demo_reentries()[0]
    calls = []

    def slow_forecast(n):
        calls.append(n)
        time.sleep(0.3)
        return "forecast"

    monkeypatch.setattr(api, "forecast", slow_forecast)
    monkeypatch.setattr(api, "corridor_from_forecast", lambda n, fc: f"zone from {fc}")
    api._forecast_cached.cache_clear()
    api._corridor_cached.cache_clear()
    try:
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(api._stored_corridor(notice)))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        api._forecast_cached.cache_clear()
        api._corridor_cached.cache_clear()
    assert results == ["zone from forecast", "zone from forecast"]
    assert len(calls) == 1


def test_warmup_covers_live_and_history_zones_quickest_first():
    notices = api._demo_warmup_notices()
    windows = [n.window_minutes for n in notices]
    assert windows == sorted(windows)
    assert {n.norad_id for n in notices} == {n.norad_id for n in demo_reentries(api._STARTED_AT)}
    # Live notices plus the extra DEMO-1 series, without repeating its newest notice.
    assert len(notices) == len(set(notices)) > len(demo_reentries())


def test_warmup_starts_only_in_demo_and_when_allowed(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(api, "_warm_demo_zones", started.set)
    with TestClient(api.app):
        pass
    assert not started.wait(0.2)  # tests set SKYFALL_WARMUP=0
    monkeypatch.setenv("SKYFALL_WARMUP", "1")
    monkeypatch.setattr(api, "_client", lambda: object())  # Space-Track: zones live on disk
    with TestClient(api.app):
        pass
    assert not started.wait(0.2)
    monkeypatch.setattr(api, "_client", lambda: None)
    with TestClient(api.app):
        pass
    assert started.wait(2)
