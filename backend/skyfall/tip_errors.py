"""How wrong TIP notices turn out to be, learned from past re-entries.

The TIP WINDOW is not a 99 % interval: over a year of notices (3d-1 analysis)
the real re-entry fell inside DECAY_EPOCH +- WINDOW only ~85 % of the time,
with errors piled up near the centre and long tails outside. So instead of
assuming a shape, SKYFALL measures it:

    z = (real re-entry - predicted re-entry) / WINDOW

and keeps, per lead time (how long before the predicted re-entry the notice
came out), a table of quantiles of z. Only those aggregate numbers ship with
the repo; the Space-Track records they come from stay in data_local/.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Lead time buckets (hours): < 6 h, 6-24 h, 1-3 days, > 3 days.
LEAD_EDGES_H: tuple[float, ...] = (6.0, 24.0, 72.0)
LEAD_LABELS: tuple[str, ...] = ("<6h", "6-24h", "1-3d", ">3d")
# Quantile levels stored per bucket: 0 %, 0.5 %, ..., 100 %.
PROBS = np.linspace(0.0, 1.0, 201)
# The final notice is the "truth" only if it pins the time down this well
# (most are post-re-entry confirmations with WINDOW of a minute or so).
MAX_TRUTH_WINDOW_MIN = 60.0

TABLE_PATH = Path(__file__).resolve().parent / "data" / "tip_error_quantiles.json"


@dataclass(frozen=True)
class TipError:
    norad_id: int
    lead_h: float  # predicted re-entry - notice issue time
    z: float  # (real - predicted) / WINDOW


def lead_bucket(lead_h: float) -> int:
    """Index into LEAD_LABELS. Notices issued after their own prediction count as < 6 h."""
    return int(np.searchsorted(LEAD_EDGES_H, lead_h, side="right"))


def tip_errors(
    tips: list[dict], exclude: frozenset[int] = frozenset()
) -> list[TipError]:
    """Errors of every notice that was followed by a precise final notice.

    tips: raw TIP records (strings, as Space-Track returns them), any order.
    exclude: objects kept out of the table, e.g. the validation case.
    """
    from skyfall.sources.spacetrack import parse_utc  # avoid an import cycle

    by_object: dict[int, list[dict]] = defaultdict(list)
    for tip in tips:
        by_object[int(tip["NORAD_CAT_ID"])].append(tip)

    errors = []
    for norad_id, series in sorted(by_object.items()):
        if norad_id in exclude or len(series) < 2:
            continue
        series.sort(key=lambda t: parse_utc(t["MSG_EPOCH"]))
        final = series[-1]
        if float(final["WINDOW"]) > MAX_TRUTH_WINDOW_MIN:
            continue
        truth = parse_utc(final["DECAY_EPOCH"])
        for tip in series[:-1]:
            window = float(tip["WINDOW"])
            if window <= 0:
                continue
            predicted = parse_utc(tip["DECAY_EPOCH"])
            errors.append(
                TipError(
                    norad_id=norad_id,
                    lead_h=_hours(predicted - parse_utc(tip["MSG_EPOCH"])),
                    z=_minutes(truth - predicted) / window,
                )
            )
    return errors


def quantile_table(errors: list[TipError]) -> dict:
    """Per lead bucket: how many notices/objects and the quantiles of z."""
    buckets = []
    for i, label in enumerate(LEAD_LABELS):
        mine = [e for e in errors if lead_bucket(e.lead_h) == i]
        if not mine:
            raise ValueError(f"No notices in lead bucket {label}")
        z = np.array([e.z for e in mine])
        buckets.append(
            {
                "lead": label,
                "n_notices": len(mine),
                "n_objects": len({e.norad_id for e in mine}),
                "z_quantiles": [round(float(q), 4) for q in np.quantile(z, PROBS)],
            }
        )
    return {
        "lead_edges_h": list(LEAD_EDGES_H),
        "probs": [round(float(p), 4) for p in PROBS],
        "buckets": buckets,
    }


class TipErrorModel:
    """Draws z for a notice from the quantile table of its lead bucket."""

    def __init__(self, table: dict):
        self.edges_h = np.array(table["lead_edges_h"], dtype=float)
        self.probs = np.array(table["probs"], dtype=float)
        self.quantiles = [np.array(b["z_quantiles"], dtype=float) for b in table["buckets"]]

    @classmethod
    def load(cls, path: Path = TABLE_PATH) -> "TipErrorModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def bucket(self, lead_h: float) -> int:
        return int(np.searchsorted(self.edges_h, lead_h, side="right"))

    def sample_z(self, lead_h: float, n: int, rng: np.random.Generator) -> np.ndarray:
        """Inverse-CDF sampling, linear between stored quantiles."""
        return self.quantile_z(lead_h, rng.uniform(0.0, 1.0, n))

    def quantile_z(self, lead_h: float, u: np.ndarray) -> np.ndarray:
        """z at cumulative probabilities `u` (inverse CDF)."""
        return np.interp(u, self.probs, self.quantiles[self.bucket(lead_h)])

    def interval(self, lead_h: float, level: float) -> tuple[float, float]:
        """Central interval of z holding `level` of the probability."""
        tail = (1.0 - level) / 2.0
        q = self.quantiles[self.bucket(lead_h)]
        return float(np.interp(tail, self.probs, q)), float(np.interp(1.0 - tail, self.probs, q))


def _hours(delta) -> float:
    return delta.total_seconds() / 3600.0


def _minutes(delta) -> float:
    return delta.total_seconds() / 60.0

