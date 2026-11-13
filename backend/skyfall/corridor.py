"""Full pipeline: notice -> breakup points -> fragments -> probability map."""

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from skyfall.closure import EASA_HALF_WIDTHS_KM, precautionary_mask, window_track
from skyfall.config import DispersionConfig, GridConfig, MonteCarloConfig
from skyfall.density import (
    DensityGrid,
    add_points,
    build_density,
    calibrated_region_mask,
    cell_areas_km2,
    empty_counts,
)
from skyfall.dispersion import footprint_stencil, scatter_fragments, spread_expected
from skyfall.models import Cell, Corridor, EasaClosure, RegionSummary, ReentryNotice
from skyfall.montecarlo import BreakupSamples, run_breakup_monte_carlo
from skyfall.track_drift import with_track_drift

MAX_BREAKUP_POINTS_OUT = 500
# Independent runs: A ranks cells, B decides where regions stop, C
# (comparison.py) grades every closure. A has no randomness at all (weighted time
# grid, expected footprint): random fragments made the ranking of
# sparse tail cells a lottery and inflated the area (+-5 h never converged).
# B and C stay random. Offsets keep their streams apart.
CALIB_SEED_OFFSET = 1_000
# Stencil points gridded at once by the ranking run (memory cap).
MAX_STENCIL_POINTS = 4_000_000
# The "price curve": each extra point of safety costs more sky than the last.
LEVELS = (90, 95, 99)


SimulationMode = Literal["random", "expected"]


@dataclass(frozen=True)
class Simulation:
    breakup: BreakupSamples
    density: DensityGrid
    n_fragments: int  # 0 in "expected" mode: no fragments, a weighted footprint


def simulate(
    notice: ReentryNotice,
    mc: MonteCarloConfig = MonteCarloConfig(),
    dispersion: DispersionConfig = DispersionConfig(),
    grid: GridConfig = GridConfig(),
    mode: SimulationMode = "random",
) -> Simulation:
    """The expensive part: re-entry times -> breakup points -> fragments -> grid.

    "random": sampled instants, random fragments (runs B and C).
    "expected": a weighted time grid, each instant spreading the expected
    footprint (run A). Same physics, no luck.
    """
    dispersion = with_track_drift(notice, dispersion)
    if mode == "expected":
        breakup = run_breakup_monte_carlo(notice, mc, stratified=True)
        res = grid.resolution_deg
        counts = empty_counts(res)
        # A wide strip spreads thousands of stencil points per instant: grid
        # them in batches so long notices stay within memory.
        batch = max(1, MAX_STENCIL_POINTS // footprint_stencil(dispersion)[0].size)
        for s in range(0, len(breakup.lat_deg), batch):
            part = slice(s, s + batch)
            lat, lon, w = spread_expected(
                breakup.lat_deg[part], breakup.lon_deg[part], breakup.heading_deg[part],
                dispersion, breakup.weight[part],
            )
            add_points(counts, lat, lon, res, w)
        return Simulation(breakup, DensityGrid(res, counts / counts.sum()), 0)

    breakup = run_breakup_monte_carlo(notice, mc)
    # Separate stream from the time sampling, still reproducible.
    rng = np.random.default_rng([mc.seed, 1])
    lat, lon = scatter_fragments(
        breakup.lat_deg, breakup.lon_deg, breakup.heading_deg, dispersion, rng
    )
    return Simulation(breakup, build_density(lat, lon, grid.resolution_deg), len(lat))


@dataclass(frozen=True)
class Forecast:
    rank: Simulation  # run A: shown on the map, orders the cells
    calib: Simulation  # run B: sets the region boundaries
    masks: dict[int, np.ndarray]  # level (90, 95, 99) -> closed cells


def forecast(
    notice: ReentryNotice,
    mc: MonteCarloConfig = MonteCarloConfig(),
    dispersion: DispersionConfig = DispersionConfig(),
    grid: GridConfig = GridConfig(),
) -> Forecast:
    rank = simulate(notice, mc, dispersion, grid, mode="expected")
    calib = simulate(notice, replace(mc, seed=mc.seed + CALIB_SEED_OFFSET), dispersion, grid)
    masks = {
        level: calibrated_region_mask(rank.density, calib.density, level / 100) for level in LEVELS
    }
    return Forecast(rank, calib, masks)


def compute_corridor(
    notice: ReentryNotice,
    mc: MonteCarloConfig = MonteCarloConfig(),
    dispersion: DispersionConfig = DispersionConfig(),
    grid: GridConfig = GridConfig(),
) -> Corridor:
    return corridor_from_forecast(notice, forecast(notice, mc, dispersion, grid))


def corridor_from_forecast(notice: ReentryNotice, fc: Forecast) -> Corridor:
    masks, density = fc.masks, fc.rank.density
    # Run A sits on an evenly spaced time grid; run B's breakup points are
    # spread like the real probability, so they are the ones to draw.
    breakup = fc.calib.breakup

    areas = cell_areas_km2(density.resolution_deg)
    regions = {
        str(level): RegionSummary(area_km2=float(areas[m].sum()), n_cells=int(m.sum()))
        for level, m in masks.items()
    }

    # Only cells inside the widest zone: the rest are never drawn and made the
    # response up to 13 MB. Calibrated zones may include cells run A left empty.
    i_lat, i_lon = np.nonzero(masks[99])
    c_lat, c_lon = density.cell_center(i_lat, i_lon)
    cells = [
        Cell(
            lat=float(la),
            lon=float(lo),
            p=float(f"{density.prob[i, j]:.4g}"),
            region=next(level for level in LEVELS if masks[level][i, j]),
        )
        for la, lo, i, j in zip(c_lat, c_lon, i_lat, i_lon)
    ]

    step = max(1, len(breakup.lat_deg) // MAX_BREAKUP_POINTS_OUT)
    points = [
        (float(a), float(b)) for a, b in zip(breakup.lat_deg[::step], breakup.lon_deg[::step])
    ]

    lat, lon = window_track(notice)
    easa = []
    for w in EASA_HALF_WIDTHS_KM:
        m = precautionary_mask(lat, lon, w, density.resolution_deg)
        e_lat, e_lon = density.cell_center(*np.nonzero(m))
        easa.append(
            EasaClosure(
                half_width_km=w,
                area_km2=float(areas[m].sum()),
                coverage=fc.calib.density.coverage(m),
                cells=[(round(float(a), 2), round(float(b), 2)) for a, b in zip(e_lat, e_lon)],
            )
        )

    return Corridor(
        norad_id=notice.norad_id,
        n_samples=len(breakup.lat_deg),
        n_failed=breakup.n_failed,
        n_fragments=fc.calib.n_fragments,
        resolution_deg=density.resolution_deg,
        regions=regions,
        cells=cells,
        breakup_points=points,
        easa=easa,
    )
