"""Fragment dispersion: from one breakup point to a cloud of impact points."""

from statistics import NormalDist

import numpy as np

from skyfall.config import DispersionConfig

EARTH_RADIUS_KM = 6371.0088  # mean radius, good enough for surface distances


def destination_point(
    lat_deg: np.ndarray, lon_deg: np.ndarray, bearing_deg: np.ndarray, distance_km: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Point reached travelling `distance_km` along a great circle (sphere)."""
    lat1, lon1 = np.radians(lat_deg), np.radians(lon_deg)
    brg = np.radians(bearing_deg)
    d = np.asarray(distance_km) / EARTH_RADIUS_KM

    lat2 = np.arcsin(np.sin(lat1) * np.cos(d) + np.cos(lat1) * np.sin(d) * np.cos(brg))
    lon2 = lon1 + np.arctan2(
        np.sin(brg) * np.sin(d) * np.cos(lat1), np.cos(d) - np.sin(lat1) * np.sin(lat2)
    )
    lon2 = (np.degrees(lon2) + 180.0) % 360.0 - 180.0
    return np.degrees(lat2), lon2


def scatter_fragments(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    heading_deg: np.ndarray,
    cfg: DispersionConfig,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Impact points: each breakup point spawns `fragments_per_sample` fragments."""
    k = cfg.fragments_per_sample
    lat = np.repeat(lat_deg, k)
    lon = np.repeat(lon_deg, k)
    heading = np.repeat(heading_deg, k)

    along = np.clip(rng.normal(cfg.along_mean_km, cfg.along_sigma_km, lat.size), 0.0, None)
    cross = rng.normal(0.0, cfg.cross_sigma_km, lat.size)

    lat, lon = destination_point(lat, lon, heading, along)
    # Sideways step, perpendicular to the track. Using the original heading is
    # fine: cross-track offsets are tens of km against ~1000 km along-track.
    return destination_point(lat, lon, heading + 90.0, cross)


def footprint_stencil(cfg: DispersionConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fixed (along_km, cross_km, weight) points: the mean of infinite fragments.

    Along-track: the clipped normal of scatter_fragments, integrated over
    `footprint_along_step_km` bins (the share clipped below 0 sits at 0 km).
    Cross-track: the normal integrated over `footprint_cross_step_km` bins,
    symmetric around the track, tails beyond 4 sigma folded into the end bins.
    The node count grows with the spread, so a wide strip has no gaps.
    """
    along_law = NormalDist(cfg.along_mean_km, cfg.along_sigma_km)
    step = cfg.footprint_along_step_km
    edges = np.arange(0.0, cfg.along_mean_km + 4 * cfg.along_sigma_km + step, step)
    cdf = np.array([along_law.cdf(e) for e in edges])
    along = np.concatenate(([0.0], (edges[:-1] + edges[1:]) / 2))
    w_along = np.concatenate(([cdf[0]], np.diff(cdf)))

    cross_law = NormalDist(0.0, cfg.cross_sigma_km)
    c_step = cfg.footprint_cross_step_km
    n_side = max(1, int(np.ceil(4 * cfg.cross_sigma_km / c_step)))
    cross = np.arange(-n_side, n_side + 1) * c_step
    c_edges = np.concatenate(([-np.inf], cross[:-1] + c_step / 2, [np.inf]))
    w_cross = np.diff([cross_law.cdf(e) if np.isfinite(e) else float(e > 0) for e in c_edges])

    a, c = np.meshgrid(along, cross, indexing="ij")
    w = np.outer(w_along, w_cross)
    return a.ravel(), c.ravel(), w.ravel() / w.sum()


def spread_expected(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    heading_deg: np.ndarray,
    cfg: DispersionConfig,
    point_weight: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every breakup point spreads the whole stencil: (lat, lon, weight), no randomness.

    Each point's stencil weights sum to its `point_weight` (1 if None). Same
    two great-circle steps as scatter_fragments.
    """
    along, cross, w = footprint_stencil(cfg)
    k = along.size
    lat = np.repeat(lat_deg, k)
    lon = np.repeat(lon_deg, k)
    heading = np.repeat(heading_deg, k)
    n = len(lat_deg)
    lat, lon = destination_point(lat, lon, heading, np.tile(along, n))
    lat, lon = destination_point(lat, lon, heading + 90.0, np.tile(cross, n))
    pw = np.ones(n) if point_weight is None else np.asarray(point_weight)
    return lat, lon, np.outer(pw, w).ravel()
