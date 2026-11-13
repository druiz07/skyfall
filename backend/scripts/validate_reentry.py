"""Hindcast a re-entry that already happened: did each closure catch it?

For every TIP issued before the confirmed re-entry, prints whether the
confirmed point falls inside SKYFALL's 99 % zone (empirical and uniform
timing) and EASA's 70 / 120 km strips, and how much sky each one closes.
Space-Track data stays in the data_local/ cache; only the summary is printed.

Usage (from backend/):  ..\\.venv\\Scripts\\python.exe scripts\\validate_reentry.py 46698
"""

import sys
import time

from skyfall.sources.spacetrack import SpaceTrackClient
from skyfall.validation import confirmation, hindcast_all

LABELS = {
    "skyfall_99": "SKYFALL",
    "skyfall_uniform_99": "SKYFALL unif.",
    "easa_70km": "EASA 70",
    "easa_120km": "EASA 120",
}


def main(norad_id: int) -> int:
    client = SpaceTrackClient.from_env()
    if client is None:
        print("Needs Space-Track credentials in .env (or cached queries).")
        return 1
    notices = client.notice_history(norad_id)
    truth = confirmation(notices)
    if truth is None:
        print(f"No confirmed re-entry for {norad_id} yet.")
        return 1
    print(
        f"{truth.name} ({norad_id}): down at {truth.decay_epoch:%Y-%m-%d %H:%M} UTC "
        f"+-{truth.window_minutes:.0f} min, point ({truth.predicted_lat:.1f}, "
        f"{truth.predicted_lon:.1f})\n"
    )

    header = f"{'issued (UTC)':<17} {'window':>8} {'lead h':>7} {'z':>6}"
    print(header + "".join(f" {label:>20}" for label in LABELS.values()))
    started = time.perf_counter()
    for h in hindcast_all(notices):
        cells = []
        for zone in h.zones:
            mark = "IN " if zone.hit else f"out {zone.miss_km:>5.0f} km"
            cells.append(f" {mark:>11} {zone.area_km2 / 1e6:>6.1f} M")
        print(
            f"{h.notice.issued_at:%Y-%m-%d %H:%M} {h.notice.window_minutes:>6.0f}m "
            f"{h.lead_hours:>7.1f} {h.z:>+6.2f}" + "".join(cells),
            flush=True,
        )
    print(f"\n(area in million km2; 'out' = distance to the zone; {time.perf_counter() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 46698))
