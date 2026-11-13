"""Monte Carlo over the re-entry instant: where is the object when it breaks up?"""

from dataclasses import dataclass
from functools import lru_cache
from statistics import NormalDist

import numpy as np

from skyfall.config import MonteCarloConfig, TimeDistribution
from skyfall.models import ReentryNotice
from skyfall.orbit import ground_track
from skyfall.tip_errors import TipErrorModel

_HEADING_STEP_MIN = 10.0 / 60.0


@dataclass(frozen=True)
class BreakupSamples:
    offsets_min: np.ndarray  # minutes relative to DECAY_EPOCH
    lat_deg: np.ndarray
    lon_deg: np.ndarray
    alt_km: np.ndarray
    heading_deg: np.ndarray  # direction of travel over the ground, clockwise from north
    n_failed: int  # samples dropped because SGP4 reported an error
    weight: np.ndarray | None = None  # probability of each instant; None = all equal


@lru_cache(maxsize=1)
def error_model() -> TipErrorModel:
    return TipErrorModel.load()


def lead_hours(notice: ReentryNotice) -> float:
    """How long before the predicted re-entry the notice came out (0 if unknown)."""
    if notice.issued_at is None:
        return 0.0
    return (notice.decay_epoch - notice.issued_at).total_seconds() / 3600.0


def spread_minutes(notice: ReentryNotice, distribution: TimeDistribution) -> float:
    """Half-width of the time span holding ~99 % of the sampled re-entry instants."""
    if distribution != "empirical":
        return notice.window_minutes
    lo, hi = error_model().interval(lead_hours(notice), 0.99)
    return (hi - lo) / 2.0 * notice.window_minutes


def sample_offsets(
    window_minutes: float,
    n: int,
    rng: np.random.Generator,
    distribution: TimeDistribution,
    lead_h: float = 0.0,
) -> np.ndarray:
    """Random offsets (minutes) from DECAY_EPOCH.

    "uniform" and "normal" stay inside [-window, +window]; "empirical" scales
    past TIP errors (in windows) by this window, tails included.
    """
    if distribution == "empirical":
        return error_model().sample_z(lead_h, n, rng) * window_minutes
    if distribution == "uniform":
        return rng.uniform(-window_minutes, window_minutes, n)
    if distribution == "normal":
        sigma = window_minutes / 2.0
        out = np.empty(0)
        while out.size < n:
            draw = rng.normal(0.0, sigma, 2 * n)
            out = np.concatenate((out, draw[np.abs(draw) <= window_minutes]))
        return out[:n]
    raise ValueError(f"Unknown time distribution: {distribution!r}")


def time_grid(
    window_minutes: float,
    distribution: TimeDistribution,
    lead_h: float = 0.0,
    step_minutes: float = 10.0 / 60.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Instants every `step_minutes`, each weighted by the probability of its slice.

    No luck, like the marks on a ruler. A fixed step keeps the breakup points
    a few tens of km apart everywhere, tails included (evenly spaced
    quantiles left ~900 km gaps in the tails). "empirical" covers its central
    99 %: the stored 0.5 % end slices stretch to outliers months away.
    """
    w = window_minutes
    if distribution == "empirical":
        model, bucket = error_model(), error_model().bucket(lead_h)
        q, probs = model.quantiles[bucket], model.probs
        lo, hi = model.interval(lead_h, 0.99)

        def cdf(z):
            return np.interp(z, q, probs)

    elif distribution == "uniform":
        lo, hi = -1.0, 1.0

        def cdf(z):
            return (z + 1.0) / 2.0

    elif distribution == "normal":
        lo, hi = -1.0, 1.0  # sigma = window / 2, truncated at +-window

        def cdf(z):
            return np.array([NormalDist(0.0, 0.5).cdf(x) for x in z])

    else:
        raise ValueError(f"Unknown time distribution: {distribution!r}")

    n = max(1, int(np.ceil((hi - lo) * w / step_minutes)))
    edges = np.linspace(lo, hi, n + 1)
    mass = np.diff(cdf(edges))
    keep = mass > 0
    return ((edges[:-1] + edges[1:]) / 2 * w)[keep], (mass / mass.sum())[keep]


def run_breakup_monte_carlo(
    notice: ReentryNotice, config: MonteCarloConfig, stratified: bool = False
) -> BreakupSamples:
    """Breakup points; `stratified` uses a weighted time grid instead (no randomness)."""
    distribution, lead_h = config.time_distribution, lead_hours(notice)
    weight = None
    if stratified:
        offsets, weight = time_grid(
            notice.window_minutes, distribution, lead_h, config.rank_step_seconds / 60.0
        )
    else:
        offsets = sample_offsets(
            notice.window_minutes,
            config.samples_for(spread_minutes(notice, distribution)),
            np.random.default_rng(config.seed),
            distribution,
            lead_h,
        )
    track = ground_track(notice.elements, notice.decay_epoch, offsets)
    # Heading from where the satellite is a few seconds later (Earth rotation included).
    ahead = ground_track(notice.elements, notice.decay_epoch, offsets + _HEADING_STEP_MIN)
    heading = _initial_bearing_deg(track.lat_deg, track.lon_deg, ahead.lat_deg, ahead.lon_deg)
    ok = track.ok & ahead.ok
    return BreakupSamples(
        offsets_min=offsets[ok],
        lat_deg=track.lat_deg[ok],
        lon_deg=track.lon_deg[ok],
        alt_km=track.alt_km[ok],
        heading_deg=heading[ok],
        n_failed=int((~ok).sum()),
        weight=None if weight is None else weight[ok],
    )


def _initial_bearing_deg(lat1, lon1, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlon = np.radians(lon2 - lon1)
    y = np.sin(dlon) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlon)
    return np.degrees(np.arctan2(y, x)) % 360.0
