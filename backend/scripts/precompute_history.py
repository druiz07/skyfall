r"""Compute and store the zone of every notice of one object, ahead of time.

A +-23 h notice takes minutes; after this the globe's history animation loads
instantly. Zones go to data_local/zones/ (git-ignored), like the Space-Track cache.

Usage (from backend/):  ..\.venv\Scripts\python.exe scripts\precompute_history.py 46698
"""

import sys
import time

from skyfall import api


def main(norad_id: int) -> None:
    _, forecasts, landed = api._history_notices(norad_id)
    print(f"NORAD {norad_id}: {len(forecasts)} notices, landed: {landed is not None}")
    for i in range(len(forecasts)):
        start = time.perf_counter()
        corridor = api.get_history_corridor(norad_id, i)
        area = corridor.regions["99"].area_km2 / 1e6
        print(f"  notice {i} +-{forecasts[i].window_minutes:g} min: 99 % zone {area:.1f} M km2"
              f" ({time.perf_counter() - start:.0f} s)")


if __name__ == "__main__":
    main(int(sys.argv[1]))
