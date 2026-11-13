"""Hindcast: would each closure have caught a re-entry that already happened?

For every notice issued before an object came down, draw the closures that
could have been drawn with what was known then, and check whether the
confirmed re-entry point falls inside each one.

Truth = the post-re-entry confirmation notice (issued after its own
DECAY_EPOCH, a WINDOW of a minute or so). Its point is where the object was
declared down; fragments spread hundreds of km around it.
"""

from dataclasses import dataclass, replace

import numpy as np

from skyfall.closure import EASA_HALF_WIDTHS_KM, precautionary_mask, window_track
from skyfall.config import DispersionConfig, GridConfig, MonteCarloConfig
from skyfall.corridor import LEVELS, forecast
from skyfall.density import cell_areas_km2
from skyfall.dispersion import EARTH_RADIUS_KM
from skyfall.models import ReentryNotice


@dataclass(frozen=True)
class ZoneCheck:
    name: str
    hit: bool  # the confirmed point lies in a closed cell
    area_km2: float
    miss_km: float  # distance to the nearest closed cell centre; 0 when hit


@dataclass(frozen=True)
class Hindcast:
    notice: ReentryNotice
    lead_hours: float  # notice issued -> confirmed re-entry
    z: float  # (true - predicted time) / WINDOW; |z| <= 1 means inside the window
    zones: list[ZoneCheck]


def is_confirmation(n: ReentryNotice) -> bool:
    """Issued after its own DECAY_EPOCH, with the point: 'it is down, here'."""
    return (
        n.issued_at is not None
        and n.issued_at >= n.decay_epoch
        and n.predicted_lat is not None
        and n.predicted_lon is not None
    )


def confirmation(notices: list[ReentryNotice]) -> ReentryNotice | None:
    """The newest confirmation notice, if the object is down."""
    confirmed = [n for n in notices if is_confirmation(n)]
    return max(confirmed, key=lambda n: n.issued_at, default=None)


def zone_check(
    name: str, mask: np.ndarray, resolution_deg: float, lat: float, lon: float
) -> ZoneCheck:
    areas = cell_areas_km2(resolution_deg)
    n_lat, n_lon = mask.shape
    i_lat = min(int((lat + 90.0) // resolution_deg), n_lat - 1)
    i_lon = int((lon + 180.0) // resolution_deg) % n_lon
    area = float(areas[mask].sum())
    if mask[i_lat, i_lon]:
        return ZoneCheck(name, True, area, 0.0)
    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        return ZoneCheck(name, False, area, float("inf"))
    c_lat = np.radians(-90.0 + (rows + 0.5) * resolution_deg)
    c_lon = np.radians(-180.0 + (cols + 0.5) * resolution_deg)
    p_lat, p_lon = np.radians(lat), np.radians(lon)
    h = (
        np.sin((c_lat - p_lat) / 2) ** 2
        + np.cos(p_lat) * np.cos(c_lat) * np.sin((c_lon - p_lon) / 2) ** 2
    )
    miss = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))
    return ZoneCheck(name, False, area, float(miss.min()))


def hindcast(
    notice: ReentryNotice,
    truth: ReentryNotice,
    mc: MonteCarloConfig = MonteCarloConfig(),
    dispersion: DispersionConfig = DispersionConfig(),
    grid: GridConfig = GridConfig(),
    include_uniform: bool = True,
) -> Hindcast:
    """Every closure for one past notice, checked against the confirmed point."""
    lat, lon = truth.predicted_lat, truth.predicted_lon
    res = grid.resolution_deg
    fc = forecast(notice, mc, dispersion, grid)
    masks = {f"skyfall_{level}": fc.masks[level] for level in sorted(LEVELS, reverse=True)}
    if include_uniform:
        masks["skyfall_uniform_99"] = forecast(
            notice, replace(mc, time_distribution="uniform"), dispersion, grid
        ).masks[99]
    t_lat, t_lon = window_track(notice)
    for w in EASA_HALF_WIDTHS_KM:
        masks[f"easa_{w:.0f}km"] = precautionary_mask(t_lat, t_lon, w, res)

    error_min = (truth.decay_epoch - notice.decay_epoch).total_seconds() / 60.0
    return Hindcast(
        notice=notice,
        lead_hours=(truth.decay_epoch - notice.issued_at).total_seconds() / 3600.0,
        z=error_min / notice.window_minutes if notice.window_minutes else float("inf"),
        zones=[zone_check(name, mask, res, lat, lon) for name, mask in masks.items()],
    )


def hindcast_all(notices: list[ReentryNotice], **kwargs) -> list[Hindcast]:
    """Hindcast every notice issued before the confirmed re-entry, oldest first."""
    truth = confirmation(notices)
    if truth is None:
        return []
    earlier = [n for n in notices if n.issued_at is not None and n.issued_at < truth.decay_epoch]
    return [hindcast(n, truth, **kwargs) for n in sorted(earlier, key=lambda n: n.issued_at)]
