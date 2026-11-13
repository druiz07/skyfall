"""Build skyfall/data/tip_error_quantiles.json from a year of TIP notices.

Reads one bulk TIP query through the Space-Track client (served from the
data_local/ cache when present, otherwise one request with your credentials),
keeps the learn half only (even NORAD ids, see skyfall/holdout.py), writes
only aggregate quantiles, and runs a held-out check inside that half:

    half the learn objects build the table, the other half test it. Does the
    central 99 % interval of z really catch ~99 % of the unseen re-entries?

Usage (from backend/):  ..\\.venv\\Scripts\\python.exe scripts\\build_tip_error_table.py
"""

import json
import math
import sys
from datetime import datetime, timezone

import numpy as np

from skyfall.holdout import BULK_PATH, LEARN_RULE, VALIDATION_NORAD, is_learn
from skyfall.sources.spacetrack import SpaceTrackClient
from skyfall.tip_errors import (
    LEAD_LABELS,
    TABLE_PATH,
    TipErrorModel,
    lead_bucket,
    quantile_table,
    tip_errors,
)

N_SPLITS = 50
LEVEL = 0.99


def main() -> int:
    client = SpaceTrackClient.from_env()
    if client is None:
        print("Needs Space-Track credentials in .env (or a cached bulk query).")
        return 1
    # A fixed snapshot: keep using the cached copy, delete it to refresh.
    # Learn half only: the odd ids are the held-out exam.
    tips = [t for t in client.query(BULK_PATH, math.inf) if is_learn(int(t["NORAD_CAT_ID"]))]
    errors = tip_errors(tips)

    table = quantile_table(errors)
    table["source"] = {
        "query": "Space-Track TIP, DECAY_EPOCH 2025-10-01..2026-10-03",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "truth": "DECAY_EPOCH of each object's final notice, when its WINDOW <= 60 min",
        "learn_split": LEARN_RULE,
        "excluded_norad": [VALIDATION_NORAD],
        "n_notices": len(errors),
        "n_objects": len({e.norad_id for e in errors}),
    }
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TABLE_PATH.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {TABLE_PATH} ({len(errors)} notices, {table['source']['n_objects']} objects)\n")

    print(f"{'lead':>6} {'notices':>8} {'objects':>8} {'in TIP':>7} {'z p0.5':>7} {'z p99.5':>8}")
    model = TipErrorModel(table)
    for i, b in enumerate(table["buckets"]):
        z = np.array([e.z for e in errors if lead_bucket(e.lead_h) == i])
        lo, hi = model.interval(_lead_of(i), LEVEL)
        print(
            f"{b['lead']:>6} {b['n_notices']:>8} {b['n_objects']:>8} "
            f"{np.mean(np.abs(z) <= 1):>7.1%} {lo:>7.2f} {hi:>8.2f}"
        )

    print(f"\nHeld-out check ({N_SPLITS} random half/half splits by object):")
    print(f"{'lead':>6} {'uniform in TIP':>15} {'empirical 99 %':>15} {'min..max':>13}")
    objects = np.array(sorted({e.norad_id for e in errors}))
    rng = np.random.default_rng(7)
    hits_uniform = {label: [] for label in LEAD_LABELS}
    hits_empirical = {label: [] for label in LEAD_LABELS}
    for _ in range(N_SPLITS):
        train_ids = set(rng.choice(objects, objects.size // 2, replace=False).tolist())
        train = [e for e in errors if e.norad_id in train_ids]
        test = [e for e in errors if e.norad_id not in train_ids]
        split_model = TipErrorModel(quantile_table(train))
        for i, label in enumerate(LEAD_LABELS):
            z = np.array([e.z for e in test if lead_bucket(e.lead_h) == i])
            lo, hi = split_model.interval(_lead_of(i), LEVEL)
            hits_uniform[label].append(np.mean(np.abs(z) <= 1))
            hits_empirical[label].append(np.mean((z >= lo) & (z <= hi)))
    for label in LEAD_LABELS:
        emp = np.array(hits_empirical[label])
        print(
            f"{label:>6} {np.mean(hits_uniform[label]):>15.1%} {emp.mean():>15.1%} "
            f"{emp.min():>6.1%}..{emp.max():.1%}"
        )
    return 0


def _lead_of(bucket: int) -> float:
    """A lead time (h) that falls in the given bucket."""
    return (0.0, 12.0, 48.0, 100.0)[bucket]


if __name__ == "__main__":
    sys.exit(main())
