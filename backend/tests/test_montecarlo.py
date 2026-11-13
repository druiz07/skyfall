from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from skyfall.config import MonteCarloConfig
from skyfall.montecarlo import (
    error_model,
    run_breakup_monte_carlo,
    sample_offsets,
    spread_minutes,
    time_grid,
)
from skyfall.sources.demo import demo_reentries

REF = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _notice(norad_id, window_minutes=None):
    notice = next(n for n in demo_reentries(REF) if n.norad_id == norad_id)
    if window_minutes is not None:
        notice = notice.model_copy(update={"window_minutes": window_minutes})
    return notice


def _occupied_lon_bins(lon_deg, width=10.0):
    return len(np.unique(np.floor(lon_deg / width)))


def test_uniform_offsets_stay_inside_window_and_are_flat():
    rng = np.random.default_rng(0)
    offsets = sample_offsets(300.0, 50_000, rng, "uniform")

    assert offsets.min() >= -300.0 and offsets.max() <= 300.0
    assert offsets.mean() == pytest.approx(0.0, abs=5.0)
    assert offsets.std() == pytest.approx(300.0 / np.sqrt(3), rel=0.02)  # flat distribution


def test_normal_offsets_stay_inside_window_and_concentrate_in_center():
    rng = np.random.default_rng(0)
    offsets = sample_offsets(300.0, 50_000, rng, "normal")

    assert offsets.min() >= -300.0 and offsets.max() <= 300.0
    assert offsets.std() < 300.0 / np.sqrt(3)


def test_unknown_distribution_is_rejected():
    with pytest.raises(ValueError):
        sample_offsets(10.0, 10, np.random.default_rng(0), "triangular")


def test_same_seed_gives_identical_results():
    notice = _notice(900002)
    a = run_breakup_monte_carlo(notice, MonteCarloConfig(n_samples=500, seed=7))
    b = run_breakup_monte_carlo(notice, MonteCarloConfig(n_samples=500, seed=7))
    c = run_breakup_monte_carlo(notice, MonteCarloConfig(n_samples=500, seed=8))

    np.testing.assert_array_equal(a.lat_deg, b.lat_deg)
    np.testing.assert_array_equal(a.lon_deg, b.lon_deg)
    assert not np.array_equal(a.lat_deg, c.lat_deg)


def test_prograde_orbit_always_heads_east():
    # A 53 deg orbit moves west-to-east, so its ground heading is between 0 and 180 deg.
    result = run_breakup_monte_carlo(_notice(900001), MonteCarloConfig(n_samples=2000))

    assert np.all((result.heading_deg > 0.0) & (result.heading_deg < 180.0))


def test_narrow_window_concentrates_points():
    # +-5 min = 10 min of flight: a short stretch of the ground track. Uniform:
    # this checks the meaning of the window, not the empirical tails.
    mc = MonteCarloConfig(n_samples=2000, time_distribution="uniform")
    result = run_breakup_monte_carlo(_notice(900001, 5.0), mc)

    assert result.n_failed == 0
    assert len(result.lat_deg) == 2000
    assert _occupied_lon_bins(result.lon_deg) <= 10


def test_wide_window_spreads_points_around_the_globe():
    # +-15 h = about 10 laps: almost every longitude is possible.
    result = run_breakup_monte_carlo(_notice(900003), MonteCarloConfig(n_samples=5000))

    assert _occupied_lon_bins(result.lon_deg) >= 34
    assert result.lat_deg.min() < -45.0 and result.lat_deg.max() > 45.0


def test_sample_count_scales_with_window():
    mc = MonteCarloConfig()
    assert mc.samples_for(43.0) == mc.min_samples  # short window: the floor
    assert mc.samples_for(900.0) == 720_000  # 1800 min total x 400
    assert MonteCarloConfig(n_samples=500).samples_for(900.0) == 500  # explicit wins


def test_empirical_offsets_fall_inside_the_window_about_85_percent_of_the_time():
    # Past TIPs: the real re-entry was inside +-WINDOW only ~85 % of the time.
    z = sample_offsets(1.0, 200_000, np.random.default_rng(0), "empirical", lead_h=12.0)

    assert 0.75 < np.mean(np.abs(z) <= 1.0) < 0.93


def test_empirical_offsets_have_a_longer_late_tail():
    # Objects come down late far more often than early.
    z = sample_offsets(1.0, 200_000, np.random.default_rng(0), "empirical", lead_h=48.0)

    assert np.quantile(z, 0.99) > 2 * -np.quantile(z, 0.01)


def test_lead_time_changes_the_empirical_spread():
    notice = _notice(900001)  # issued 3 h before the predicted re-entry
    early = notice.model_copy(update={"issued_at": notice.decay_epoch - timedelta(days=5)})

    assert spread_minutes(notice, "uniform") == notice.window_minutes
    assert spread_minutes(early, "empirical") != spread_minutes(notice, "empirical")


def test_sample_count_is_capped():
    mc = MonteCarloConfig()
    assert mc.samples_for(1e7) == mc.max_samples
    assert mc.samples_for(1.0) == mc.min_samples


@pytest.mark.parametrize("distribution", ["empirical", "uniform", "normal"])
def test_time_grid_is_a_weighted_ruler(distribution):
    offsets, weight = time_grid(60.0, distribution, lead_h=12.0, step_minutes=0.5)

    assert weight.sum() == pytest.approx(1.0)
    assert np.all(weight > 0)
    assert np.allclose(np.diff(offsets), np.diff(offsets)[0])  # evenly spaced
    assert np.diff(offsets)[0] <= 0.5


def test_time_grid_follows_its_distribution():
    offsets, weight = time_grid(60.0, "uniform", step_minutes=1.0)
    assert offsets.min() > -60.0 and offsets.max() < 60.0
    assert np.allclose(weight, weight[0])

    offsets, weight = time_grid(60.0, "empirical", lead_h=12.0, step_minutes=1.0)
    lo, hi = error_model().interval(12.0, 0.99)
    assert offsets.min() == pytest.approx(lo * 60.0, abs=1.0)
    assert offsets.max() == pytest.approx(hi * 60.0, abs=1.0)


def test_stratified_run_has_no_randomness():
    notice = _notice(900002)
    a = run_breakup_monte_carlo(notice, MonteCarloConfig(seed=1), stratified=True)
    b = run_breakup_monte_carlo(notice, MonteCarloConfig(seed=2), stratified=True)

    np.testing.assert_array_equal(a.lat_deg, b.lat_deg)
    np.testing.assert_array_equal(a.weight, b.weight)
    assert a.weight.sum() == pytest.approx(1.0)
