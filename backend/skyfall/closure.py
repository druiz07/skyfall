"""Precautionary airspace closure: the whole ground track of the window, widened.

Today's practice (EASA SIB 2022-09, Long March 5B, Nov 2022): restrict a strip
of 70 to 120 km on each side of every re-entry pass inside the uncertainty
window. We rasterise that strip on the same grid as the SKYFALL map so both
closures pay the same discretisation cost: a cell is closed when its centre is
within half_width_km of the track.
"""

import numpy as np

from skyfall.dispersion import EARTH_RADIUS_KM
from skyfall.models import ReentryNotice
from skyfall.orbit import ground_track

# EASA SIB 2022-09: "minimum 70 km and up to 120 km on each side".
EASA_HALF_WIDTHS_KM = (70.0, 120.0)
# ~16 km between track points: the strip edge sags < 2 km between them.
TRACK_STEP_S = 2.0
# Same SIB: restrict "a few minutes before and after the time window". 5 min
# also covers fragments thrown ~800-1600 km ahead (~2-4 min of ground track).
MARGIN_MIN = 5.0


def window_track(
    notice: ReentryNotice, margin_min: float = MARGIN_MIN, step_s: float = TRACK_STEP_S
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-satellite points every step_s across DECAY_EPOCH +- (WINDOW + margin)."""
    w = notice.window_minutes + margin_min
    offsets = np.append(np.arange(-w, w, step_s / 60.0), w)
    track = ground_track(notice.elements, notice.decay_epoch, offsets)
    return track.lat_deg[track.ok], track.lon_deg[track.ok]


def precautionary_mask(
    lat_deg: np.ndarray, lon_deg: np.ndarray, half_width_km: float, resolution_deg: float
) -> np.ndarray:
    """Grid cells (n_lat, n_lon) whose centre lies within half_width_km of a track point."""
    n_lat = int(round(180.0 / resolution_deg))
    n_lon = int(round(360.0 / resolution_deg))
    c_lat = -90.0 + (np.arange(n_lat) + 0.5) * resolution_deg
    reach_deg = np.degrees(half_width_km / EARTH_RADIUS_KM)
    h = np.sin(half_width_km / EARTH_RADIUS_KM / 2) ** 2  # haversine of the radius

    order = np.argsort(lat_deg)
    lat_s = np.asarray(lat_deg)[order]
    lon_s = np.asarray(lon_deg)[order]
    mask = np.zeros((n_lat, n_lon), dtype=bool)
    # Row by row. On one row a disc covers a contiguous run of cell centres, so
    # each track point only needs its longitude half-span (from the haversine
    # formula solved for dlon), not a distance to every cell.
    for i, phi in enumerate(c_lat):
        lo = np.searchsorted(lat_s, phi - reach_deg)
        hi = np.searchsorted(lat_s, phi + reach_deg, side="right")
        if lo == hi:
            continue
        p1, p2 = np.radians(phi), np.radians(lat_s[lo:hi])
        rhs = (h - np.sin((p2 - p1) / 2) ** 2) / (np.cos(p1) * np.cos(p2))
        keep = rhs >= 0
        if not keep.any():
            continue
        half = np.degrees(2 * np.arcsin(np.sqrt(np.minimum(rhs[keep], 1.0))))
        lon = lon_s[lo:hi][keep]
        # Centres j with |centre_j - lon| <= half; j may run past either edge.
        j0 = np.ceil((lon - half + 180.0) / resolution_deg - 0.5).astype(int)
        j1 = np.floor((lon + half + 180.0) / resolution_deg - 0.5).astype(int)
        if (j1 - j0 + 1 >= n_lon).any():
            mask[i] = True
            continue
        # Runs on a tripled row (to absorb the wrap), then folded back.
        ext = np.zeros(3 * n_lon + 1)
        np.add.at(ext, j0 + n_lon, 1.0)
        np.add.at(ext, j1 + n_lon + 1, -1.0)
        covered = np.cumsum(ext[:-1]).reshape(3, n_lon) > 0.5
        mask[i] = covered.any(axis=0)
    return mask
