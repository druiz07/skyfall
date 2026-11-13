"""Build skyfall/data/track_drift.json: sideways drift of aging element sets.

Learn half only: objects with an even NORAD id and a confirmed re-entry in the
bulk TIP query (see build_tip_error_table.py). Odd ids are kept for the
held-out exam (scripts/exam_reentries.py); 46698 is never used.
One gp_history request per object (cached in data_local/); only the
aggregate table is written to the repo.

Usage (from backend/):  ..\\.venv\\Scripts\\python.exe scripts\\build_track_drift_table.py
"""

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone

from skyfall.sources.spacetrack import (
    GP_LOOKBACK,
    SpaceTrackClient,
    SpaceTrackError,
    notice_from_tip,
    parse_utc,
)
from skyfall.holdout import BULK_PATH, VALIDATION_NORAD, is_learn
from skyfall.track_drift import TABLE_PATH, drift_table, element_age_hours, measure_drift
from skyfall.validation import confirmation

def confirmed_objects(client: SpaceTrackClient, keep) -> dict[int, list]:
    """NORAD id -> notices (with elements), for objects with a confirmed re-entry."""
    tips_by_obj = defaultdict(list)
    for tip in client.query(BULK_PATH, math.inf):
        tips_by_obj[int(tip["NORAD_CAT_ID"])].append(tip)
    out = {}
    for norad_id, tips in sorted(tips_by_obj.items()):
        if not keep(norad_id) or not any(
            t.get("LAT") and parse_utc(t["MSG_EPOCH"]) >= parse_utc(t["DECAY_EPOCH"]) for t in tips
        ):
            continue
        issued = [parse_utc(t["MSG_EPOCH"]) for t in tips]
        try:
            gp_rows = client.gp_history(norad_id, min(issued) - GP_LOOKBACK, max(issued))
        except SpaceTrackError as exc:
            print(f"{norad_id}: {exc}")
            continue
        notices = []
        for tip in tips:
            try:
                notices.append(notice_from_tip(tip, gp_rows))
            except (SpaceTrackError, KeyError, ValueError):
                pass  # no elements published before this notice
        if confirmation(notices) is not None:
            out[norad_id] = notices
    return out


def main() -> int:
    client = SpaceTrackClient.from_env()
    if client is None:
        print("Needs Space-Track credentials in .env (or cached queries).")
        return 1
    objects = confirmed_objects(client, is_learn)
    samples = []
    for notices in objects.values():
        truth = confirmation(notices)
        for n in notices:
            if n.issued_at < truth.decay_epoch:
                samples.append((element_age_hours(n), measure_drift(n, truth)))

    table = drift_table(samples)
    table["source"] = {
        "query": "Space-Track TIP, DECAY_EPOCH 2025-10-01..2026-10-03, + gp_history",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "objects": "even NORAD ids with a post-re-entry confirmation (learn half)",
        "excluded_norad": [VALIDATION_NORAD],
        "n_objects": len(objects),
        "n_notices": len(samples),
    }
    TABLE_PATH.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {TABLE_PATH} ({len(samples)} notices, {len(objects)} objects)\n")
    print(f"{'age':>7} {'n':>5} {'lost':>5} {'p50':>6} {'p90':>6} {'p99':>6} {'sigma':>6}  (km)")
    for b in table["buckets"]:
        print(
            f"{b['age']:>7} {b['n']:>5} {b['n_lost']:>5} {b['p50_km']:>6.0f} "
            f"{b['p90_km']:>6.0f} {b['p99_km']:>6.0f} {b['sigma_km']:>6.0f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
