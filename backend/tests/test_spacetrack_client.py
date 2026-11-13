"""Space-Track client without network: a fake opener answers instead of the server."""

import io
import json

import pytest

from skyfall.sources.spacetrack import (
    RateLimiter,
    SpaceTrackClient,
    SpaceTrackError,
    load_env,
    select_client,
)

# Invented record: tests never use real Space-Track data.
FAKE_ROWS = [{"NORAD_CAT_ID": "999999", "WINDOW": "60"}]


class FakeOpener:
    def __init__(self, login_body='""'):
        self.urls = []
        self.login_body = login_body

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        body = self.login_body if request.full_url.endswith("/login") else json.dumps(FAKE_ROWS)
        return io.BytesIO(body.encode())


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _client(tmp_path, opener=None, clock=None):
    clock = clock or FakeClock()
    return SpaceTrackClient(
        "user",
        "pw",
        cache_dir=tmp_path,
        limiter=RateLimiter(clock=clock, sleep=clock.sleep),
        opener=opener or FakeOpener(),
        wall_clock=clock,
    )


def test_logs_in_once_then_queries(tmp_path):
    opener = FakeOpener()
    client = _client(tmp_path, opener)

    assert client.query("class/tip/limit/1", ttl_s=60) == FAKE_ROWS
    client.query("class/tip/limit/2", ttl_s=60)

    assert [u.rsplit("/", 1)[-1] for u in opener.urls] == ["login", "json", "json"]
    assert opener.urls[1].endswith("/basicspacedata/query/class/tip/limit/1/format/json")


def test_fresh_cache_skips_the_network_and_stale_cache_refetches(tmp_path):
    clock = FakeClock()
    opener = FakeOpener()
    client = _client(tmp_path, opener, clock)

    client.query("class/tip", ttl_s=3600)
    clock.t += 1800
    client.query("class/tip", ttl_s=3600)
    assert len(opener.urls) == 2  # login + first query only

    clock.t += 3600
    client.query("class/tip", ttl_s=3600)
    assert len(opener.urls) == 3


def test_failed_login_raises(tmp_path):
    client = _client(tmp_path, FakeOpener(login_body='{"Login":"Failed"}'))
    with pytest.raises(SpaceTrackError, match="login failed"):
        client.query("class/tip", ttl_s=60)


def test_rate_limiter_spaces_requests():
    clock = FakeClock()
    limiter = RateLimiter(min_interval_s=2.5, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    assert clock.t == pytest.approx(1005.0)  # two waits of 2.5 s


def test_rate_limiter_refuses_past_hourly_budget_then_recovers():
    clock = FakeClock()
    limiter = RateLimiter(min_interval_s=0, max_per_hour=3, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    with pytest.raises(SpaceTrackError, match="Hourly budget"):
        limiter.acquire()
    clock.t += 3600
    limiter.acquire()


def test_load_env_reads_key_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nSPACETRACK_USER=a@b.c\nSPACETRACK_PASSWORD="p=w"\n\n')
    assert load_env(env) == {"SPACETRACK_USER": "a@b.c", "SPACETRACK_PASSWORD": "p=w"}
    assert load_env(tmp_path / "missing") == {}


class DownOpener(FakeOpener):
    def open(self, request, timeout):
        raise OSError("network down")


def test_expired_cache_is_served_when_space_track_is_down(tmp_path):
    clock = FakeClock()
    _client(tmp_path, FakeOpener(), clock).query("class/tip", ttl_s=60)
    clock.t += 3600

    assert _client(tmp_path, DownOpener(), clock).query("class/tip", ttl_s=60) == FAKE_ROWS
    with pytest.raises(SpaceTrackError, match="network down"):
        _client(tmp_path, DownOpener(), clock).query("class/gp", ttl_s=60)  # nothing cached


CREDS = {"SPACETRACK_USER": "u", "SPACETRACK_PASSWORD": "p"}


def test_select_client_follows_skyfall_source():
    assert select_client({}) is None
    assert isinstance(select_client(CREDS), SpaceTrackClient)
    assert select_client({**CREDS, "SKYFALL_SOURCE": "demo"}) is None
    assert isinstance(select_client({**CREDS, "SKYFALL_SOURCE": "spacetrack"}), SpaceTrackClient)
    with pytest.raises(SpaceTrackError, match="missing"):
        select_client({"SKYFALL_SOURCE": "spacetrack"})
    with pytest.raises(ValueError, match="SKYFALL_SOURCE"):
        select_client({"SKYFALL_SOURCE": "live"})


class RefusingOpener(FakeOpener):
    def open(self, request, timeout):
        if request.full_url.endswith("/login"):
            return super().open(request, timeout)
        self.urls.append(request.full_url)
        return io.BytesIO(b'[{"error": "You\'ve violated your query rate limit."}]')


def test_refusal_raises_and_is_never_cached(tmp_path):
    clock = FakeClock()
    with pytest.raises(SpaceTrackError, match="rate limit"):
        _client(tmp_path, RefusingOpener(), clock).query("class/gp", ttl_s=60)
    assert not list(tmp_path.glob("*.json"))
    assert _client(tmp_path, FakeOpener(), clock).query("class/gp", ttl_s=60) == FAKE_ROWS


def test_rate_limiter_budget_survives_a_restart(tmp_path):
    clock = FakeClock()
    log = tmp_path / "requests.log"
    first = RateLimiter(min_interval_s=0, max_per_hour=3, clock=clock, sleep=clock.sleep, log_path=log)
    for _ in range(2):
        first.acquire()
    second = RateLimiter(min_interval_s=0, max_per_hour=3, clock=clock, sleep=clock.sleep, log_path=log)
    second.acquire()
    with pytest.raises(SpaceTrackError, match="Hourly budget"):
        second.acquire()
    clock.t += 3600
    RateLimiter(min_interval_s=0, max_per_hour=3, clock=clock, sleep=clock.sleep, log_path=log).acquire()
