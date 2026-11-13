"""How far sideways an old element set puts the ground track, by element age.

A notice's elements (the orbit "recipe") were measured hours or days before
the re-entry. Carried forward to the moment of re-entry, the ground track they
draw passes some distance to the side of where the object really came down:
a small error in where the satellite is along its orbit means the Earth has
turned a little more or less underneath it. Measured on past re-entries
(scripts/build_track_drift_table.py): ~15 km for recipes under 6 h old,
~80 km at 1-2 days, a few hundred km after 3 days.

The fragment strip is then widened sideways by this drift (added in
quadrature to the fragments' own cross-track spread).
"""

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from skyfall.config import DispersionConfig
from skyfall.dispersion import EARTH_RADIUS_KM
from skyfall.models import ReentryNotice
from skyfall.orbit import ground_track

TABLE_PATH = Path(__file__).resolve().parent / "data" / "track_drift.json"

# Element age buckets (h): <6, 6-12, 12-24, 1-2 d, 2-3 d, 3-5 d, >5 d.
AGE_EDGES_H = (6.0, 12.0, 24.0, 48.0, 72.0, 120.0)
AGE_LABELS = ("<6h", "6-12h", "12-24h", "1-2d", "2-3d", "3-5d", ">5d")
# Closest approach searched within +-SEARCH_MIN of the true re-entry time.
SEARCH_MIN = 15.0
# Further than this the recipe has lost track of where the object is along
# its orbit: a timing error, not a sideways one. Left out of the fit.
LOST_KM = 1000.0
# sigma from the 90th percentile of |drift| (robust to the few lost cases).
Z90 = 1.6449


def age_bucket(age_h: float) -> int:
    return int(np.searchsorted(AGE_EDGES_H, age_h, side="right"))


def element_age_hours(notice: ReentryNotice) -> float:
    """Age of the notice's elements at its predicted re-entry: known when issued."""
    return (notice.decay_epoch - notice.elements.epoch).total_seconds() / 3600.0


def measure_drift(notice: ReentryNotice, truth: ReentryNotice) -> float:
    """Closest approach (km) of the notice's ground track to the confirmed point.

    Searched within +-SEARCH_MIN of the true time, so it measures the sideways
    offset, not the along-track one. inf if SGP4 fails over the whole span.
    """
    offsets = np.arange(-SEARCH_MIN * 60, SEARCH_MIN * 60 + 1, 2.0) / 60.0
    track = ground_track(notice.elements, truth.decay_epoch, offsets)
    p_lat, p_lon = math.radians(truth.predicted_lat), math.radians(truth.predicted_lon)
    lat, lon = np.radians(track.lat_deg), np.radians(track.lon_deg)
    h = np.sin((lat - p_lat) / 2) ** 2 + math.cos(p_lat) * np.cos(lat) * np.sin((lon - p_lon) / 2) ** 2
    d = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))
    d[~track.ok] = np.inf
    return float(d.min())


def drift_table(samples: list[tuple[float, float]]) -> dict:
    """(element age h, drift km) pairs -> per-bucket sigma, monotone in age."""
    buckets = []
    sigma_floor = 0.0
    for i, label in enumerate(AGE_LABELS):
        d = np.array([km for age, km in samples if age_bucket(age) == i])
        kept = d[d < LOST_KM]
        if kept.size == 0:
            raise ValueError(f"no drift samples for element age {label}")
        p50, p90, p99 = np.percentile(kept, [50, 90, 99])
        # Older recipes never drift less than younger ones.
        sigma_floor = max(sigma_floor, p90 / Z90)
        buckets.append(
            {
                "age": label,
                "n": int(d.size),
                "n_lost": int(d.size - kept.size),
                "p50_km": round(float(p50), 1),
                "p90_km": round(float(p90), 1),
                "p99_km": round(float(p99), 1),
                "sigma_km": round(sigma_floor, 1),
            }
        )
    return {"age_edges_h": list(AGE_EDGES_H), "buckets": buckets}


@dataclass(frozen=True)
class TrackDriftModel:
    sigma_km_by_bucket: tuple[float, ...]

    @classmethod
    def load(cls, path: Path = TABLE_PATH) -> "TrackDriftModel":
        table = json.loads(path.read_text(encoding="utf-8"))
        return cls(tuple(b["sigma_km"] for b in table["buckets"]))

    def sigma_km(self, age_h: float) -> float:
        return self.sigma_km_by_bucket[age_bucket(age_h)]


_MODEL: TrackDriftModel | None = None


def drift_model() -> TrackDriftModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = TrackDriftModel.load()
    return _MODEL


def with_track_drift(notice: ReentryNotice, dispersion: DispersionConfig) -> DispersionConfig:
    """Widen the sideways spread by the expected drift of this notice's elements."""
    if not dispersion.track_drift:
        return dispersion
    drift = drift_model().sigma_km(element_age_hours(notice))
    return replace(
        dispersion,
        cross_sigma_km=math.hypot(dispersion.cross_sigma_km, drift),
        track_drift=False,  # applied; never twice
    )
