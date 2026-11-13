from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from skyfall.api import app
from skyfall.comparison import compute_comparison
from skyfall.config import DispersionConfig, MonteCarloConfig
from skyfall.sources.demo import demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
client = TestClient(app)


def _by_name(comparison):
    return {c.name: c for c in comparison.closures}


@pytest.fixture(scope="module", params=[900001, 900002])
def comparison(request):
    notice = next(n for n in demo_reentries(REF) if n.norad_id == request.param)
    return compute_comparison(notice)


def test_skyfall_99_zone_holds_99_percent_of_fresh_fragments(comparison):
    # Graded on run C, which took no part in drawing the zone.
    assert _by_name(comparison)["skyfall_99"].coverage == pytest.approx(0.99, abs=0.003)


def test_price_curve_more_safety_costs_more_sky(comparison):
    # Each zone is graded on run C; it must reach its level and nest in the next.
    c = _by_name(comparison)
    for level in (90, 95, 99):
        assert c[f"skyfall_{level}"].coverage == pytest.approx(level / 100, abs=0.005)
    assert c["skyfall_90"].area_km2 < c["skyfall_95"].area_km2 < c["skyfall_99"].area_km2


def test_wider_easa_strip_closes_more_sky_and_covers_at_least_as_much(comparison):
    c = _by_name(comparison)
    assert c["easa_120km"].area_km2 > 1.4 * c["easa_70km"].area_km2
    assert c["easa_120km"].coverage >= c["easa_70km"].coverage


def test_easa_strips_miss_the_late_tail(comparison):
    # Empirical timing: re-entries outside the notice window land on laps the
    # strip (window +- 5 min) never covers, however wide it is.
    c = _by_name(comparison)
    assert c["easa_120km"].coverage < c["skyfall_99"].coverage - 0.05


def test_easa_120_covers_everything_if_window_and_orbit_were_exact():
    # Uniform timing = trust the window blindly, as today's closures do; no
    # track drift = trust the elements blindly too.
    notice = next(n for n in demo_reentries(REF) if n.norad_id == 900001)
    c = _by_name(
        compute_comparison(
            notice,
            MonteCarloConfig(time_distribution="uniform"),
            DispersionConfig(track_drift=False),
        )
    )

    assert c["easa_120km"].coverage > 0.999
    assert c["skyfall_99"].coverage == pytest.approx(0.99, abs=0.003)


def test_area_vs_skyfall_is_relative_to_the_skyfall_zone(comparison):
    c = _by_name(comparison)
    assert c["skyfall_99"].area_vs_skyfall_pct == 0.0
    expected = 100 * (c["easa_120km"].area_km2 / c["skyfall_99"].area_km2 - 1)
    assert c["easa_120km"].area_vs_skyfall_pct == pytest.approx(expected)


def test_comparison_endpoint():
    body = client.get("/reentries/900001/comparison").json()

    assert [c["name"] for c in body["closures"]] == [
        "skyfall_90", "skyfall_95", "skyfall_99", "easa_70km", "easa_120km"
    ]
    assert [c["half_width_km"] for c in body["closures"]] == [None, None, None, 70.0, 120.0]
    assert body["window_minutes"] == 43.0


def test_comparison_unknown_norad_is_404():
    assert client.get("/reentries/1/comparison").status_code == 404
