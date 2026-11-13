"""Probability map on a lat/lon grid and the 95 % / 99 % regions.

A region at level L is the smallest set of cells holding at least L of the
probability (fill the hottest cells first). Its area is the sum of the true
cell areas on a spherical Earth: cells shrink towards the poles.

Drawn on one simulation alone, a region is tailored to that run's luck: the
sparse edge cells it picks differ from run to run, so fresh fragments land
inside only ~97-98 % of the time for a "99 %" region. calibrated_region_mask
fixes this: one run ranks the cells, an independent run decides where to stop.
"""

from dataclasses import dataclass

import numpy as np

from skyfall.dispersion import EARTH_RADIUS_KM


def cell_areas_km2(resolution_deg: float) -> np.ndarray:
    """Area of every grid cell, shape (n_lat, n_lon)."""
    lat_edges = np.radians(np.arange(-90.0, 90.0 + resolution_deg / 2, resolution_deg))
    band = EARTH_RADIUS_KM**2 * np.radians(resolution_deg) * np.diff(np.sin(lat_edges))
    n_lon = int(round(360.0 / resolution_deg))
    return np.repeat(band[:, None], n_lon, axis=1)


@dataclass(frozen=True)
class DensityGrid:
    resolution_deg: float
    prob: np.ndarray  # (n_lat, n_lon), sums to 1; row 0 = southernmost band

    def region_mask(self, level: float) -> np.ndarray:
        flat = self.prob.ravel()
        order = np.argsort(flat)[::-1]
        cumulative = np.cumsum(flat[order])
        n_cells = int(np.searchsorted(cumulative, level - 1e-12) + 1)
        mask = np.zeros(flat.size, dtype=bool)
        mask[order[:n_cells]] = True
        return mask.reshape(self.prob.shape)

    def coverage(self, mask: np.ndarray) -> float:
        """Fraction of the simulated fragments that fall inside the closed cells."""
        return float(self.prob[mask].sum())

    def region_area_km2(self, level: float) -> float:
        return float(cell_areas_km2(self.resolution_deg)[self.region_mask(level)].sum())

    def cell_center(self, i_lat: np.ndarray, i_lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = self.resolution_deg
        return -90.0 + (i_lat + 0.5) * r, -180.0 + (i_lon + 0.5) * r


# Tie-break between equally sparse cells: neighbourhood density (Gaussian,
# sigma in cells). Used only for ordering, never added to the probability:
# smoothing the map itself widens the ~50 km strip and inflates the area +35 %.
TIE_BREAK_SIGMA_CELLS = 1.0


def _smooth(prob: np.ndarray, sigma_cells: float) -> np.ndarray:
    r = int(np.ceil(4 * sigma_cells))
    offsets = np.arange(-r, r + 1)
    kernel = np.exp(-0.5 * (offsets / sigma_cells) ** 2)
    kernel /= kernel.sum()
    out = sum(w * np.roll(prob, d, axis=1) for d, w in zip(offsets, kernel))  # lon wraps
    padded = np.pad(out, ((r, r), (0, 0)), mode="edge")  # lat clamps at the poles
    n = prob.shape[0]
    return sum(w * padded[r + d : r + d + n] for d, w in zip(offsets, kernel))


def calibrated_region_mask(rank: DensityGrid, calib: DensityGrid, level: float) -> np.ndarray:
    """Cells ordered by `rank`, kept until `calib` (an independent run) holds `level`."""
    smooth = _smooth(rank.prob, TIE_BREAK_SIGMA_CELLS)
    # Lexicographic: own probability first, neighbourhood only to break ties.
    order = np.lexsort((-smooth.ravel(), -rank.prob.ravel()))
    cumulative = np.cumsum(calib.prob.ravel()[order])
    n_cells = int(np.searchsorted(cumulative, level - 1e-12) + 1)
    mask = np.zeros(rank.prob.size, dtype=bool)
    mask[order[:n_cells]] = True
    return mask.reshape(rank.prob.shape)


def build_density(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    resolution_deg: float,
    weights: np.ndarray | None = None,
) -> DensityGrid:
    """Probability per cell: share of points (or of their `weights`) inside it."""
    counts = add_points(empty_counts(resolution_deg), lat_deg, lon_deg, resolution_deg, weights)
    return DensityGrid(resolution_deg=resolution_deg, prob=counts / counts.sum())


def empty_counts(resolution_deg: float) -> np.ndarray:
    return np.zeros((int(round(180.0 / resolution_deg)), int(round(360.0 / resolution_deg))))


def add_points(
    counts: np.ndarray,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    resolution_deg: float,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Add points (or their `weights`) to a counts grid, in place; returns it.

    Lets big point clouds be gridded in batches (see corridor.simulate).
    """
    n_lat, n_lon = counts.shape
    i_lat = np.clip(((np.asarray(lat_deg) + 90.0) // resolution_deg).astype(int), 0, n_lat - 1)
    lon = (np.asarray(lon_deg) + 180.0) % 360.0
    i_lon = np.clip((lon // resolution_deg).astype(int), 0, n_lon - 1)
    np.add.at(counts, (i_lat, i_lon), 1.0 if weights is None else weights)
    return counts
