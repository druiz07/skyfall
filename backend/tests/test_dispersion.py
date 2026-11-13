from dataclasses import replace

import numpy as np
import pytest

from skyfall.config import DispersionConfig
from skyfall.dispersion import (
    destination_point,
    footprint_stencil,
    scatter_fragments,
    spread_expected,
)

KM_PER_DEG = 6371.0088 * np.pi / 180.0  # ~111.2 km


@pytest.mark.parametrize(
    "bearing, lat, lon", [(0.0, 1.0, 0.0), (90.0, 0.0, 1.0), (180.0, -1.0, 0.0)]
)
def test_destination_point_moves_one_degree(bearing, lat, lon):
    got_lat, got_lon = destination_point(
        np.array([0.0]), np.array([0.0]), np.array([bearing]), np.array([KM_PER_DEG])
    )
    assert got_lat[0] == pytest.approx(lat, abs=1e-9)
    assert got_lon[0] == pytest.approx(lon, abs=1e-9)


def test_no_spread_means_fragments_land_on_breakup_point():
    cfg = DispersionConfig(along_mean_km=0.0, along_sigma_km=0.0, cross_sigma_km=0.0)
    lat, lon = scatter_fragments(
        np.array([10.0, -20.0]), np.array([30.0, 170.0]), np.array([45.0, 300.0]),
        cfg, np.random.default_rng(0),
    )
    np.testing.assert_allclose(lat, np.repeat([10.0, -20.0], cfg.fragments_per_sample))
    np.testing.assert_allclose(lon, np.repeat([30.0, 170.0], cfg.fragments_per_sample))


def test_fragments_travel_downrange_in_a_long_thin_footprint():
    # Breakup on the equator flying due east: fragments land east, in a thin strip.
    cfg = DispersionConfig(fragments_per_sample=20_000)
    lat, lon = scatter_fragments(
        np.array([0.0]), np.array([0.0]), np.array([90.0]), cfg, np.random.default_rng(1)
    )

    assert lon.min() >= -1e-9  # never behind the breakup point
    assert lon.mean() * KM_PER_DEG == pytest.approx(cfg.along_mean_km, rel=0.05)
    assert lat.std() * KM_PER_DEG == pytest.approx(cfg.cross_sigma_km, rel=0.05)
    assert lon.std() > 10 * lat.std()  # much longer than wide


def test_footprint_stencil_matches_the_random_fragments():
    cfg = DispersionConfig()
    along, cross, w = footprint_stencil(cfg)
    fragments = np.clip(np.random.default_rng(0).normal(800.0, 400.0, 1_000_000), 0.0, None)

    assert w.sum() == pytest.approx(1.0)
    assert np.sum(w * along) == pytest.approx(fragments.mean(), rel=0.01)
    # Binning adds ~step^2 / 12 of variance: within a few percent.
    assert np.sqrt(np.sum(w * cross**2)) == pytest.approx(cfg.cross_sigma_km, rel=0.05)
    assert np.sum(w * cross) == pytest.approx(0.0, abs=1e-9)
    # Along-track nodes closer than a grid cell (~55 km): no cell is skipped.
    assert np.all(np.diff(np.unique(along)) <= cfg.footprint_along_step_km + 1e-9)


def test_wide_strip_gets_more_cross_nodes_never_gaps():
    for sigma in (25.0, 83.0, 184.0):
        cfg = replace(DispersionConfig(), cross_sigma_km=sigma)
        _, cross, w = footprint_stencil(cfg)
        assert np.all(np.diff(np.unique(cross)) <= cfg.footprint_cross_step_km + 1e-9)
        assert cross.max() >= 4 * sigma - cfg.footprint_cross_step_km
        assert np.sqrt(np.sum(w * cross**2)) == pytest.approx(sigma, rel=0.05)


def test_expected_spread_keeps_each_point_weight():
    cfg = DispersionConfig()
    lat, lon, w = spread_expected(
        np.zeros(2), np.zeros(2), np.full(2, 90.0), cfg, point_weight=np.array([0.25, 0.75])
    )
    k = footprint_stencil(cfg)[0].size

    assert lat.size == lon.size == w.size == 2 * k
    assert w[:k].sum() == pytest.approx(0.25) and w[k:].sum() == pytest.approx(0.75)
    assert np.all(lon >= 0.0)  # heading east: everything lands downrange
