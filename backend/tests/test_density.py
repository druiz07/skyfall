import numpy as np
import pytest

from skyfall.density import EARTH_RADIUS_KM, build_density, calibrated_region_mask, cell_areas_km2


def test_cell_areas_add_up_to_earth_surface():
    areas = cell_areas_km2(0.5)
    assert areas.shape == (360, 720)
    assert areas.sum() == pytest.approx(4 * np.pi * EARTH_RADIUS_KM**2, rel=1e-9)


def test_single_cell_cloud_gives_single_cell_region():
    grid = build_density(np.full(100, 40.2), np.full(100, -3.7), resolution_deg=0.5)

    assert grid.region_mask(0.99).sum() == 1
    assert grid.prob.sum() == pytest.approx(1.0)


def test_regions_hold_their_mass_and_are_nested():
    rng = np.random.default_rng(3)
    lat = rng.normal(10.0, 3.0, 50_000)
    lon = rng.normal(20.0, 3.0, 50_000)
    grid = build_density(lat, lon, resolution_deg=0.5)

    m95, m99 = grid.region_mask(0.95), grid.region_mask(0.99)
    assert grid.prob[m95].sum() >= 0.95
    assert grid.prob[m99].sum() >= 0.99
    assert np.all(m99[m95])  # 95 % region is inside the 99 % one
    assert grid.region_area_km2(0.99) > grid.region_area_km2(0.95) > 0


def test_longitude_180_wraps_into_grid():
    grid = build_density(np.array([0.1]), np.array([180.0]), resolution_deg=0.5)
    assert grid.prob.sum() == pytest.approx(1.0)


def test_coverage_counts_fragments_inside_the_mask():
    # Three fragments in one cell, one in another: closing only the first cell covers 75 %.
    grid = build_density(np.array([10.1, 10.2, 10.3, -40.0]), np.array([5.1, 5.2, 5.3, 60.0]), 0.5)
    hot = grid.prob == grid.prob.max()

    assert grid.coverage(hot) == pytest.approx(0.75)
    assert grid.coverage(np.ones_like(hot)) == pytest.approx(1.0)
    assert grid.coverage(np.zeros_like(hot)) == 0.0


def test_calibrated_region_stops_on_the_calibration_run():
    # Rank run: cell X hot, cell Y cold. Calibration run: all mass in Y.
    # Reaching 99 % of the calibration run therefore needs both cells.
    rank = build_density(np.array([10.1, 10.2, 10.3, -40.0]), np.array([5.1, 5.2, 5.3, 60.0]), 0.5)
    calib = build_density(np.array([-40.0]), np.array([60.0]), 0.5)

    assert rank.region_mask(0.7).sum() == 1
    assert calibrated_region_mask(rank, calib, 0.7).sum() == 2


def test_calibrated_region_breaks_ties_by_neighbourhood():
    # Two lone fragments with equal counts; the one next to the cluster goes first.
    lat = np.array([10.1] * 20 + [10.6, -40.1])
    lon = np.array([5.1] * 20 + [5.1, 60.1])
    rank = build_density(lat, lon, 0.5)
    mask = calibrated_region_mask(rank, rank, 21 / 22)

    def cell(la, lo):  # grid indices on the 0.5 deg grid
        return int((la + 90) // 0.5), int((lo + 180) // 0.5)

    assert mask.sum() == 2
    assert mask[cell(10.6, 5.1)] and not mask[cell(-40.1, 60.1)]


def test_weights_count_as_shares_of_probability():
    grid = build_density(np.array([0.1, 10.1]), np.array([0.1, 10.1]), 1.0, np.array([1.0, 3.0]))

    assert grid.prob.max() == pytest.approx(0.75)
    assert grid.prob.sum() == pytest.approx(1.0)
